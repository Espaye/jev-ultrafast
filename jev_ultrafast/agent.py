"""The complete agent loop. Typed choices, observable state, bounded execution."""

import base64
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from .browser import Browser, StalePage
from .console import say
from .model import (
    action_space,
    answer_context,
    choose,
    field_context,
    field_text,
    helper_key,
    map_context,
    map_place,
    spoken_answer,
)
from .questions import MAX_STEPS

WEB_SEARCH = {
    "id": "web_search",
    "kind": "search",
    # Naming the site makes "is this request about {site}?" a concrete comparison. The earlier wording
    # ("only when ... its own search box cannot advance the request") kept unrelated requests in a site's search.
    "label": "Open an empty Google search to search the whole web instead of {site}. Choose it when the "
    "request is about something {site} does not cover; {site}'s own search box only finds {site} content.",
}
# Every page takes key presses; the key itself is a choice among these, never model text.
KEY_ACTIONS = [
    {"id": "key_" + key.lower(), "kind": "key", "key": key, "label": label}
    for key, label in [
        ("Enter", "Enter: submit or confirm"), ("Escape", "Escape: close a dialog or menu"),
        ("ArrowUp", "Arrow up"), ("ArrowDown", "Arrow down"), ("ArrowLeft", "Arrow left"),
        ("ArrowRight", "Arrow right"), ("Backspace", "Backspace: delete the last typed character"),
        ("Tab", "Tab: move focus to the next control"),
    ]
]
TYPE_KEYS = {
    "id": "type_keys",
    "kind": "keys",
    "label": "Type letters on the keyboard into the page itself, for a page that takes key presses but has no "
    "text field to fill (such as a word game). A small LLM supplies the letters from the goal.",
}
GO_BACK = {
    "id": "go_back",
    "kind": "back",
    "label": "Go back to the previous page, like the browser's Back button. Only when the current request asks to "
    "go back, return or close something opened; never to finish or re-check another request.",
}
EARLIER_REQUESTS = 5
CYCLE_REPEATS = 3
STALE_REPEATS = 2
# One action repeated over and over, on a page that changes every time, escapes CYCLE_REPEATS: from_view holds
# the page text, so a re-rendering list (a recommendation filter) and a feed that scrolls to the next video
# both look like a new situation at every step.
# Five is measured, not guessed. Across the 635 requests recorded under artifacts/, the longest run of
# identical consecutive actions in a request that PASSED is two, for clicks and for scrolls alike; failures
# reach five and eight clicks, and nine, fourteen, sixteen and twenty-six scrolls.
ACTION_REPEATS = 5
NAVIGATION_REPEATS = 3
# Only where repeating one action is never progress. A game presses one arrow all game, a puzzle types letter
# after letter, and a map plays round after round through the same Next button, so those kinds are left alone.
GUARDED_KINDS = {"click", "scroll"}
# A key or click that changed nothing is not offered again on that same page: it would change nothing again.
# 2048 ignores an arrow against a wall for good, and Google's search button under an emptied field was
# clicked three times in a row, which ended a run that typing into the field could still have rescued.
INERT_KINDS = {"key", "click"}


def one_click_request(goal):
    """A literal, single click request is complete when that click visibly changes the page."""
    marker = '\nCurrent request ("this" means what the page showed when it was asked; '
    request = goal.rsplit(marker, 1)[-1]
    if request != goal:
        request = request.partition("): ")[2]
    request = request.strip()
    starts_with_click = re.match(
        r"^(?:(?:please|kindly)\s+|(?:can|could|would)\s+you\s+)*click\b", request, re.I
    )
    return bool(starts_with_click) and not re.search(r"\b(?:and|then|after|before|also)\b", request, re.I)


def repeated_navigation(history):
    """Catch a changing-page loop even when timers or other dynamic text defeat the view fingerprint."""
    if not history:
        return False
    last = history[-1]
    if last.get("kind") != "click" or last.get("from_url") == last.get("url"):
        return False
    edge = (last.get("from_url"), last.get("url"), last.get("action"))
    return sum(
        (h.get("from_url"), h.get("url"), h.get("action")) == edge for h in history
    ) >= NAVIGATION_REPEATS


def view(page, action):
    """What the model saw and did, without DOM node ids: client-side apps rebuild elements on every visit."""
    seen = [page["url"], page["text"], action["kind"], action["label"]]
    return hashlib.sha256(json.dumps(seen).encode()).hexdigest()


def searches_the_web(url):
    """Google's own search pages, empty or full of results, already search the whole web. WEB_SEARCH there only
    swapped the results for an empty page: results that happened to show no link to the site a request named
    ("On GitHub: ...") read as "google.com cannot help", and the run went back to the page it started on."""
    parts = urlsplit(url)
    google = re.fullmatch(r"(www\.)?google(\.[a-z]{2,3}){1,2}", parts.hostname or "")
    return google is not None and parts.path in {"/", "/search", "/webhp"}


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
    answer_later = False  # See report().

    def __init__(self, url, goals, *, record_dir=None, screenshots=False, web_search=False, answer_later=False):
        task = goals.strip() if isinstance(goals, str) else "\n".join(goals).strip()
        if not task:
            raise ValueError("Supply a task")
        plan = [task]
        self.pending_text = None
        self.browser = Browser(url)
        self.record_dir = Path(record_dir) if record_dir else None
        self.screenshots = screenshots or bool(record_dir)
        self.answer_later = answer_later
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
            answer=None,
            answer_error=None,
            answer_pending=False,
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
        if self.state.get("web_search") and not searches_the_web(page["url"]):
            site = urlsplit(page["url"]).hostname or "this site"
            site = site.removeprefix("www.")
            page["actions"].append({**WEB_SEARCH, "label": WEB_SEARCH["label"].format(site=site)})
        page["actions"].extend([*KEY_ACTIONS, TYPE_KEYS])
        if self.state["browser"].can_go_back():
            page["actions"].append(GO_BACK)
        return page

    def report(self):
        """The run has stopped, finished or not. elapsed_ms is its own time, without the answer that follows:
        that call can take seconds (an OpenRouter provider stall took 15) and is not browsing. With answer_later
        the answer waits for command("answer"), so the inspector stops its clock here and says it is answering;
        the library and the suites keep one call that returns with the answer."""
        state = self.state
        state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
        if self.answer_later:
            state["answer_pending"] = True
            return self.snapshot()
        return self.read_out()

    def read_out(self):
        """What the run says out loud, for a finished request and for one that ran out of moves alike.
        A stopped run is not silence: the page it stopped on still holds the score, the result, or how far it
        got, and this helper is the only thing that reads it. The run has ended either way; a failed answer is
        reported as such, never replaced by a guess."""
        state = self.state
        state["answer_pending"] = False
        # Whether the run can speak is the answer helper's own question: it resolves ANSWER_MODEL_API_KEY,
        # then HELPER_API_KEY, then TEXT_MODEL_API_KEY. Gating on the last name alone left a configuration
        # that sets only HELPER_API_KEY -- which helper_endpoint documents as enough -- silently mute.
        if helper_key("ANSWER_MODEL"):
            try:
                document = state["browser"].document_text()
            except (StalePage, RuntimeError):
                document = ""  # The visible text still holds what the run ended on.
            try:
                answer, helper = spoken_answer(
                    answer_context(
                        state["plan"][-1],
                        state["page"],
                        state["history"],
                        document,
                        outcome="finished" if state["status"] == "done" else "stopped",
                    )
                )
            except (ValueError, RuntimeError) as exc:
                state["answer_error"] = str(exc)
            else:
                state["answer"] = answer
                state["text_calls"].append({**helper, "field": "spoken answer", "value": answer})
        return self.snapshot()

    def new_task(self, goal, url=None):
        """Continue the conversation in the same tab: the next request starts where the last one ended."""
        goal = goal.strip()
        if not goal:
            raise ValueError("Supply a task")
        state = self.state
        # Only a request Jev reported done is described as done; a stopped one may be asked again.
        outcome = "done" if state["status"] == "done" else "not finished"
        if state["status"] == "done" and state.get("answer"):
            # "And tomorrow?" refers to what Jev said, not only to what it did.
            outcome += f"; answered: {state['answer'][:300]}"
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
            answer=None,
            answer_error=None,
            answer_pending=False,
            inert=None,
            rejected=None,
            decisions=[],
            text_calls=[],
            elapsed_ms=0,
            started_at=None,
            stale_repeats=0,
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
            acting = False
            try:
                self.command("predict", {})
                acting = True
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

                say(
                    f"STALE: {exc} | "
                    f"JEV={decision.get('latency_ms', '?')} ms | "
                    f"choice={choice} | "
                    f"target={action.get('label') if action else choice}"
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

                say(
                    f"  URL changed: {old_page.get('url') != new_page.get('url')}\n"
                    f"  marker changed: {old_page.get('marker') != new_page.get('marker')}\n"
                    f"  added controls: {added}\n"
                    f"  removed controls: {removed}"
                )

                # A rejected action on a page that did not change gets the same input, so the model repeats it.
                stuck = acting and old_page.get("marker") == new_page.get("marker")
                state["stale_repeats"] = state.get("stale_repeats", 0) + 1 if stuck else 0
                if stuck and choice:
                    # A rejection never reaches the model: nothing executed, so no history entry records it, and
                    # an unchanged page hands it the same input and gets the same choice back. Withholding the
                    # refused target is how it finds another way in -- Enter on the field it just filled.
                    rejected = state.get("rejected") or {}
                    ids = rejected["ids"] if rejected.get("fingerprint") == new_page["fingerprint"] else []
                    state["rejected"] = {"fingerprint": new_page["fingerprint"], "ids": [*ids, choice]}
                if state["stale_repeats"] >= STALE_REPEATS:
                    say(f"BLOCKED: {choice} was rejected {STALE_REPEATS} times on an unchanged page")
                    state["status"] = "blocked"

                state["page"] = new_page
                state["elapsed_ms"] = round(
                    (time.perf_counter() - state["started_at"]) * 1000
                )
                return self.report() if state["status"] == "blocked" else self.snapshot()
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
            page = state["page"]
            if state.get("map_declined") == page["fingerprint"]:
                # The helper that sees this exact page found nothing to place; offering the map again repeats it.
                page = {**page, "actions": [a for a in page["actions"] if a["kind"] != "place"]}
            inert = state.get("inert") or {}
            if inert.get("fingerprint") == page["fingerprint"]:
                # A key or click that changed nothing on this exact page would change nothing again.
                page = {**page, "actions": [a for a in page["actions"] if a["id"] not in inert["ids"]]}
            rejected = state.get("rejected") or {}
            if rejected.get("fingerprint") == page["fingerprint"]:
                # The executor refused these targets on this exact page (covered or gone); it would refuse again.
                page = {**page, "actions": [a for a in page["actions"] if a["id"] not in rejected["ids"]]}
            last = state["history"][-1] if state["history"] else None
            if last and last["kind"] == "place" and last["page_changed"] is not False:
                # Like a filled field's value: the map holds the point placed by the last action, until another
                # action (confirming it, the next round) runs.
                page = {**page, "actions": [
                    {**a, "value": f"point placed: {last['text']}"} if a["kind"] == "place" else a
                    for a in page["actions"]
                ]}
            state["decision"] = choose(page, state["goal"], state["history"])
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
                return self.report()
            action = next(a for a in page["actions"] if a["id"] == selected)
            if len(state["history"]) >= MAX_STEPS:
                state["status"] = "blocked"
                self.report()
                raise ValueError(f"Stopped at the {MAX_STEPS}-action demo budget")
            text, helper, place = None, None, None
            if action["kind"] == "place":
                if not state["browser"].fresh(page):
                    raise StalePage("Page changed before choosing a map location. Choose again.")
                context = {"map": map_context(state["goal"], page, state["history"]), "view": page["fingerprint"]}
                if self.pending_text and self.pending_text[0] == context:
                    _, place, helper = self.pending_text
                else:
                    place, helper = map_place(context["map"], state["browser"].screenshot())
                    self.pending_text = (context, place, helper)
                    state["text_calls"].append(
                        {**helper, "field": action["label"], "value": place["place"] if place else None}
                    )
                if place is None:
                    # The helper saw no location to place (a scored round still titled "Place your guess").
                    # Nothing ran; recording that lets the next choice move on, and the no-progress stop bounds it.
                    self.pending_text = None
                    state["map_declined"] = page["fingerprint"]
                    state["history"].append({
                        "step": len(state["history"]) + 1,
                        "action": action["label"],
                        "kind": "place",
                        "choice": selected,
                        "text": "not placed: the page asks for no map location now",
                        "page_changed": False,
                        "url": page["url"],
                        "from_view": view(page, action),
                        "latency_ms": decision["latency_ms"],
                        "text_helper": helper["model"],
                        "text_latency_ms": helper["latency_ms"],
                        "elapsed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                    })
                    repeated = state["history"][-3:]
                    stuck = len(repeated) == 3 and all(h["page_changed"] is False for h in repeated)
                    state["status"] = "blocked" if stuck else "ready"
                    return self.report() if stuck else self.snapshot()
                text = f"{place['place']} ({place['lat']:.2f}, {place['lng']:.2f})"
            elif action["kind"] in {"fill", "keys"}:
                # A textbox has its own identity/value/state guard. Dynamic content elsewhere (for example a
                # quiz countdown) must not make every text-helper call stale before it can type.
                freshness_target = action if action["kind"] == "fill" else None
                if not state["browser"].fresh(page, freshness_target):
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
            if place:
                state["browser"].act(action, page, place=place)
            else:
                state["browser"].act(action, page, text=text)
            self.pending_text = None
            state["stale_repeats"] = 0
            state["rejected"] = None
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
                    "from_url": page["url"],
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
            if action["kind"] in INERT_KINDS and not state["history"][-1]["page_changed"]:
                inert = state.get("inert") or {}
                ids = inert.get("ids", []) if inert.get("fingerprint") == page["fingerprint"] else []
                state["inert"] = {"fingerprint": page["fingerprint"], "ids": [*ids, action["id"]]}
            if state["record"] and state["page"]["screenshot"]:
                (self.record_dir / f"{state['elapsed_ms']:06d}.jpg").write_bytes(
                    base64.b64decode(state["page"]["screenshot"])
                )
            if (
                action["kind"] == "click"
                and state["history"][-1]["page_changed"]
                and one_click_request(state["goal"])
            ):
                say("DONE: the requested click changed the page")
                state["status"] = "done"
                state["plan_index"] = len(state["plan"])
                return self.report()
            repeated = state["history"][-3:]
            # A cycle (home -> article -> home -> ...) changes the page every step, so also stop when the
            # same action runs a third time from a page that looked the same.
            cycling = action["kind"] != "wait" and sum(
                h.get("from_view") == view(page, action) for h in state["history"]
            ) >= CYCLE_REPEATS
            # Choosing one target this many times in a row is not progress on any page: a filter that
            # re-renders its own list, a feed that scrolls to the next video for ever.
            hammering = (
                action["kind"] in GUARDED_KINDS
                and len(state["history"]) >= ACTION_REPEATS
                and all(
                    h["kind"] == action["kind"] and h["action"] == action["label"]
                    for h in state["history"][-ACTION_REPEATS:]
                )
            )
            if hammering:
                say(f"BLOCKED: {action['label'][:60]!r} was chosen {ACTION_REPEATS} times in a row")
            navigation_loop = repeated_navigation(state["history"])
            if navigation_loop:
                say(
                    f"BLOCKED: navigation from {state['history'][-1]['from_url'][:80]!r} to "
                    f"{state['history'][-1]['url'][:80]!r} repeated {NAVIGATION_REPEATS} times"
                )
            state["status"] = (
                "blocked"
                if cycling
                or hammering
                or navigation_loop
                or len(repeated) == 3
                and all(
                    h["page_changed"] is False and h["kind"] != "wait" for h in repeated
                )
                else "ready"
            )
            if state["status"] == "blocked":
                return self.report()
        elif name == "answer":
            if not state.get("answer_pending"):
                raise ValueError("No answer is waiting")
            return self.read_out()
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
