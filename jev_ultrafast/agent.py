"""The complete agent loop. Typed choices, observable state, bounded execution."""

import base64
import hashlib
import json
import time
from pathlib import Path

from .browser import SEARCH_URL, Browser, StalePage
from .model import action_space, choose, field_context, field_text
from .questions import MAX_STEPS

WEB_SEARCH = {
    "id": "web_search",
    "kind": "search",
    "label": "Leave this page for an empty Google search. Only when nothing on the current page "
    "(links, tabs such as Images or Videos, buttons, its own search box) can advance the request.",
}
EARLIER_REQUESTS = 5
CYCLE_REPEATS = 3


def view(page, action):
    """What the model saw and did, without DOM node ids: client-side apps rebuild elements on every visit."""
    seen = [page["url"], page["text"], action["kind"], action["label"]]
    return hashlib.sha256(json.dumps(seen).encode()).hexdigest()


def follow_up_goal(earlier, request):
    """A follow-up can refer to earlier requests ("the channel"); they are context, not work."""
    lines = "\n".join(f"- {goal}" for goal in earlier[-EARLIER_REQUESTS:])
    return (
        "Earlier requests in this conversation (context only; do not redo finished ones):\n"
        # "Continuing from the page that is open now" made the model restart on every page it opened
        # (article -> home to re-check -> article ...). Recent actions are progress, not a fresh start.
        f'{lines}\nCurrent request ("this" means what the page showed when it was asked; '
        f"recent actions are progress on it): {request}"
    )


class Agent:
    def __init__(self, url, goals, *, record_dir=None, screenshots=False, web_search=False):
        task = goals.strip() if isinstance(goals, str) else "\n".join(goals).strip()
        if not task:
            raise ValueError("Supply a task")
        plan = [task]
        self.pending_text = None
        self.browser = Browser(url)
        self.record_dir = Path(record_dir) if record_dir else None
        self.screenshots = screenshots or bool(record_dir)
        self.state = {"browser": self.browser, "web_search": web_search}
        try:
            page = self.observe()
        except Exception:
            self.browser.close()
            raise
        self.state.update(
            goal="\n".join(plan),
            page=page,
            decision=None,
            history=[],
            status="ready",
            plan=plan,
            plan_index=0,
            decisions=[],
            text_calls=[],
            elapsed_ms=0,
            started_at=None,
            record=bool(self.record_dir),
        )
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
        if self.record_dir and page["screenshot"]:
            (self.record_dir / "000000.jpg").write_bytes(
                base64.b64decode(page["screenshot"])
            )

    def observe(self):
        page = self.state["browser"].observe(screenshot=self.screenshots)
        if self.state.get("web_search") and not page["url"].startswith(SEARCH_URL):
            page["actions"].append(WEB_SEARCH)
        return page

    def new_task(self, goal, url=None):
        """Continue the conversation in the same tab: the next request starts where the last one ended."""
        goal = goal.strip()
        if not goal:
            raise ValueError("Supply a task")
        state = self.state
        # Only a request Jev reported done is described as done; a stopped one may be asked again.
        outcome = "done" if state["status"] == "done" else "not finished"
        earlier = [*state.get("earlier", []), f"{state['plan'][-1]} ({outcome})"]
        if url:
            state["browser"].navigate(url)
        self.pending_text = None
        state.update(
            goal=follow_up_goal(earlier, goal),
            earlier=earlier,
            plan=[*state["plan"], goal],
            plan_index=len(state["plan"]),
            page=self.observe(),
            decision=None,
            history=[],
            status="ready",
            decisions=[],
            text_calls=[],
            elapsed_ms=0,
            started_at=None,
        )
        return self.snapshot()

    def snapshot(self):
        return {
            **{k: v for k, v in self.state.items() if k != "browser"},
            "elements": action_space(self.state["page"]["actions"])[0],
        }

    def command(self, name, body=None):
        body = body or {}
        state = self.state
        if name == "tick":
            try:
                self.command("predict", {})
                return self.command(
                    "act", {"fingerprint": state["page"]["fingerprint"]}
                )
            except StalePage as exc:
                old_page = state["page"]

                decision = state["decisions"][-1] if state["decisions"] else {}
                choice = decision.get("choice")

                action = next(
                    (a for a in old_page.get("actions", []) if a.get("id") == choice),
                    None,
                )

                print(
                    f"STALE: {exc} | "
                    f"JEV={decision.get('latency_ms', '?')} ms | "
                    f"choice={choice} | "
                    f"target={action.get('label') if action else choice}",
                    flush=True,
                )

                state["decision"] = None
                state["status"] = "ready"

                new_page = self.observe()

                old_actions = {
                    (a.get("kind"), a.get("label"))
                    for a in old_page.get("actions", [])
                }
                new_actions = {
                    (a.get("kind"), a.get("label"))
                    for a in new_page.get("actions", [])
                }

                added = list(new_actions - old_actions)[:10]
                removed = list(old_actions - new_actions)[:10]

                print(
                    f"  URL changed: {old_page.get('url') != new_page.get('url')}\n"
                    f"  marker changed: {old_page.get('marker') != new_page.get('marker')}\n"
                    f"  added controls: {added}\n"
                    f"  removed controls: {removed}",
                    flush=True,
                )

                state["page"] = new_page
                state["elapsed_ms"] = round(
                    (time.perf_counter() - state["started_at"]) * 1000
                )
                return self.snapshot()
        elif name == "predict":
            if not state["browser"]:
                raise ValueError("Start a demo first")
            if state["started_at"] is None:
                state["started_at"] = time.perf_counter()
            if not state["browser"].fresh(state["page"]):
                state["page"] = self.observe()
            state["decision"] = None
            if state["status"] in {"done", "blocked"}:
                raise ValueError("This run has stopped. Start a fresh demo.")
            if len(state["decisions"]) >= MAX_STEPS * 2:
                raise ValueError("Reached the demo's model-call budget")
            state["decision"] = choose(state["page"], state["goal"], state["history"])
            state["decisions"].append(
                {
                    **state["decision"],
                    "fingerprint": state["page"]["fingerprint"],
                    "elapsed_ms": round(
                        (time.perf_counter() - state["started_at"]) * 1000
                    ),
                }
            )
            state["status"] = "predicted"
        elif name == "act":
            decision, page = state["decision"], state["page"]
            if not decision or body.get("fingerprint") != page["fingerprint"]:
                raise ValueError("Observe and choose before acting")
            # Consume once, before any mutation or model call. A retry cannot double-click.
            state["decision"] = None
            state["status"] = "ready"
            selected = decision["choice"]
            if selected in {"DONE", "BLOCKED"}:
                if not state["browser"].fresh(page):
                    state["status"] = "ready"
                    raise StalePage("Page changed since the decision. Choose again.")
                state["status"] = "done" if selected == "DONE" else "blocked"
                state["plan_index"] = len(state["plan"]) - 1 + int(selected == "DONE")
                state["elapsed_ms"] = round(
                    (time.perf_counter() - state["started_at"]) * 1000
                )
                return self.snapshot()
            action = next(a for a in page["actions"] if a["id"] == selected)
            if len(state["history"]) >= MAX_STEPS:
                state["status"] = "blocked"
                raise ValueError(f"Stopped at the {MAX_STEPS}-action demo budget")
            text, helper = None, None
            if action["kind"] == "fill":
                if not state["browser"].fresh(page):
                    raise StalePage(
                        "Page changed before text generation. Choose again."
                    )
                context = field_context(state["goal"], action, page, state["history"])
                if self.pending_text and self.pending_text[0] == context:
                    _, text, helper = self.pending_text
                else:
                    text, helper = field_text(context)
                    self.pending_text = (context, text, helper)
                    state["text_calls"].append(
                        {**helper, "field": action["label"], "value": text}
                    )
            # Browser.act checks freshness immediately before input, including after text generation.
            state["browser"].act(action, page, text=text)
            self.pending_text = None
            state["elapsed_ms"] = round(
                (time.perf_counter() - state["started_at"]) * 1000
            )
            # Record execution before observing. A stale post-action observation must not erase the action.
            state["history"].append(
                {
                    "step": len(state["history"]) + 1,
                    "action": action["label"],
                    "kind": action["kind"],
                    "choice": selected,
                    "probability": decision["probabilities"][selected],
                    "confidence": decision["confidence"],
                    "latency_ms": decision["latency_ms"],
                    "text": text,
                    "text_helper": helper["model"] if helper else None,
                    "text_latency_ms": helper["latency_ms"] if helper else 0,
                    "operation": decision["operation"],
                    "target": decision["target"],
                    "page_changed": None,
                    "url": page["url"],
                    "from_view": view(page, action),
                    "usage": decision["usage"],
                    "executed_ms": round(
                        (time.perf_counter() - state["started_at"]) * 1000
                    ),
                    "elapsed_ms": state["elapsed_ms"],
                }
            )
            state["page"] = self.observe()
            state["elapsed_ms"] = round(
                (time.perf_counter() - state["started_at"]) * 1000
            )
            state["history"][-1].update(
                page_changed=state["page"]["fingerprint"] != page["fingerprint"],
                url=state["page"]["url"],
                elapsed_ms=state["elapsed_ms"],
            )
            if state["record"] and state["page"]["screenshot"]:
                (self.record_dir / f"{state['elapsed_ms']:06d}.jpg").write_bytes(
                    base64.b64decode(state["page"]["screenshot"])
                )
            repeated = state["history"][-3:]
            # A cycle (home -> article -> home -> ...) changes the page every step, so also stop when the
            # same action runs a third time from a page that looked the same.
            cycling = action["kind"] != "wait" and sum(
                h.get("from_view") == view(page, action) for h in state["history"]
            ) >= CYCLE_REPEATS
            state["status"] = (
                "blocked"
                if cycling
                or len(repeated) == 3
                and all(
                    h["page_changed"] is False and h["kind"] != "wait" for h in repeated
                )
                else "ready"
            )
        else:
            raise ValueError("Unknown command")
        return self.snapshot()

    def run(self):
        while self.state["status"] not in {"done", "blocked"}:
            yield self.command("tick")

    def close(self):
        self.browser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
