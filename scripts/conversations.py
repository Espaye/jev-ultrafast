"""Run spoken-style conversations the way the inspector does, and check every request independently.

Each conversation starts in a fresh tab: on the site a request names, otherwise on a Google search.
Follow-ups continue in the same tab from where the previous request ended. A request passes only when
its check holds on the final page; Jev's DONE is recorded but never counted as proof.

    uv run --env-file .env python scripts/conversations.py artifacts/conversations/run-1
    uv run --env-file .env python scripts/conversations.py artifacts/video --only youtube --record

Makes paid model calls. Requests are the text Chrome's speech recognition hands the inspector;
speech recognition itself is not part of this measurement.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from browser_harness.helpers import drain_events

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jev_ultrafast import Agent  # noqa: E402
from jev_ultrafast.browser import SEARCH_URL  # noqa: E402
from jev_ultrafast.console import say  # noqa: E402

# The same pattern app.js uses to spot a website named in a request.
SITE = re.compile(r"(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,24}(?![a-z0-9-])(?:/[^\s\"'<>]*)?", re.I)
TICKS = 40  # Per request. The inspector allows 120; a stuck request here costs less.


def site_in(request):
    match = SITE.search(request)
    if not match:
        return None
    site = match.group(0).rstrip(".,;:!?)")
    return site if "://" in site else "https://" + site


def playing(page):
    return "[video, playing]" in page["text"]


def images(page):
    return re.search(r"[?&](udm=(2|imgs)|tbm=isch)(&|$)", page["url"]) is not None


def top_story(first_page):
    """Hacker News' first story title, read from the page before Jev acts."""
    return next(a["label"] for a in first_page["actions"] if a["kind"] == "click" and a["role"] == "link"
                and a["rect"]["y"] > 20 and a["rect"]["w"] > 150)


# (name, [(request, check(final_page, first_page) -> bool, what the check means)])
CONVERSATIONS = [
    ("news", [
        ("look up the latest news about the war in Yemen",
         lambda p, _: "yemen" in (p["url"] + p["title"] + p["text"]).lower() and "google.com/?" not in p["url"],
         "Yemen news: search results or an article about it"),
        ("play the video",
         lambda p, _: playing(p) or "vid:" in p["url"],
         "a video playing on the page, or open in Google's video player"),
    ]),
    ("hackernews", [
        ("go to news.ycombinator.com and open the comments of the top story",
         lambda p, first: "item?id=" in p["url"] and top_story(first) in p["text"],
         "the comment page of the story that was first on the front page"),
    ]),
    ("youtube", [
        ("go to youtube.com and search for the moon landing",
         lambda p, _: "youtube.com/results" in p["url"] and "moon" in p["url"].lower(),
         "YouTube results for a moon landing query"),
        ("play the first video",
         lambda p, _: "youtube.com/watch" in p["url"] and playing(p),
         "a YouTube video playing"),
        ("open the channel of this video",
         lambda p, _: re.search(r"youtube\.com/(@|channel/|c/)", p["url"]) is not None,
         "a YouTube channel page"),
    ]),
    ("wikipedia", [
        ("find the Wikipedia article about the Eiffel Tower",
         lambda p, _: "wikipedia.org/wiki/Eiffel_Tower" in p["url"],
         "the Eiffel Tower article"),
        ("now open the article about the man who designed it",
         lambda p, _: re.search(r"wikipedia\.org/wiki/(Gustave_Eiffel|Maurice_Koechlin|%C3%89mile_Nouguier)",
                                p["url"]) is not None,
         "the article about Eiffel, Koechlin or Nouguier"),
    ]),
    ("images", [
        ("look up a picture of a cow",
         lambda p, _: "cow" in p["url"].lower() and images(p),
         "Google Images results for cow"),
        ("show me sheep instead",
         lambda p, _: "sheep" in p["url"].lower() and images(p),
         "Google Images results for sheep"),
    ]),
]


class Screencast:
    """Continuous frames with browser timestamps, following the run into a new tab when a link opens one."""

    def __init__(self, agent, folder):
        self.agent, self.folder, self.errors, self.metadata = agent, folder, [], {}
        self.session, self.epoch, self.stop = None, time.time(), threading.Event()
        folder.mkdir(parents=True, exist_ok=True)
        self.thread = threading.Thread(target=self.capture, daemon=True)
        self.thread.start()

    def capture(self):
        try:
            while not self.stop.is_set():
                if self.agent.browser.session != self.session:
                    self.session = self.agent.browser.session
                    self.agent.browser.call("Page.startScreencast", format="jpeg", quality=80,
                                            maxWidth=1120, maxHeight=780, everyNthFrame=2)
                for event in drain_events():
                    if event["method"] != "Page.screencastFrame" or event.get("session_id") != self.session:
                        continue
                    p = event["params"]
                    ms = max(0, round((p["metadata"]["timestamp"] - self.epoch) * 1000))
                    (self.folder / f"{ms:07d}.jpg").write_bytes(base64.b64decode(p["data"]))
                    # Chrome may capture the whole window surface; the renderer crops the page out of it.
                    self.metadata[f"{ms:07d}"] = p["metadata"]
                    self.agent.browser.call("Page.screencastFrameAck", sessionId=p["sessionId"])
                self.stop.wait(0.015)
        except Exception as error:
            self.errors.append(str(error))

    def close(self):
        time.sleep(0.08)
        self.stop.set()
        self.thread.join(timeout=3)
        (self.folder / "metadata.json").write_text(json.dumps(self.metadata), encoding="utf-8")
        try:
            self.agent.browser.call("Page.stopScreencast")
        except Exception:
            pass


def run_request(agent, clock):
    """Tick until done/blocked like the inspector's Run automatically, with a smaller cap."""
    started = time.perf_counter()
    status, error = "cap", None
    for _ in range(TICKS):
        try:
            agent.command("tick")
        except Exception as exc:
            status, error = "error", f"{type(exc).__name__}: {exc}"
            break
        if agent.state["status"] in {"done", "blocked"}:
            status = agent.state["status"]
            break
    return {
        "status": status,
        "error": error,
        "started_s": round(started - clock, 3),
        "seconds": round(time.perf_counter() - started, 3),
        "actions": [h["action"] for h in agent.state["history"]],
        # When each action executed, on the conversation clock the screencast also uses.
        "action_times_s": [
            round(started - clock + (agent.state["started_at"] - started) + h["executed_ms"] / 1000, 3)
            for h in agent.state["history"]
        ],
        "model_calls": len(agent.state["decisions"]),
        "text_calls": len(agent.state["text_calls"]),
    }


def run_conversation(name, turns, folder, record):
    clock = time.perf_counter()
    first = turns[0][0]
    start = site_in(first) or SEARCH_URL
    results, screencast = [], None
    with Agent(start, first, web_search=True) as agent:
        first_page = agent.state["page"]
        if record:
            screencast = Screencast(agent, folder / "screencast")
            screencast.epoch = time.time()
            clock = time.perf_counter()
        try:
            for i, (request, check, meaning) in enumerate(turns):
                if i:
                    agent.new_task(request, site_in(request))
                result = run_request(agent, clock)
                page = agent.browser.observe(screenshot=False)
                result.update(request=request, check=meaning, url=page["url"],
                              passed=bool(check(page, first_page)))
                results.append(result)
                say(f"  {'PASS' if result['passed'] else 'FAIL'} {result['status']:7} "
                    f"{result['seconds']:6.2f}s  {request!r} -> {page['url'][:80]}")
        finally:
            if screencast:
                screencast.close()
    return {"name": name, "start": start, "requests": results,
            "recording_errors": screencast.errors if screencast else []}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--only", help="Run one conversation by name")
    parser.add_argument("--record", action="store_true", help="Capture a screencast for rendering")
    args = parser.parse_args()
    args.folder.mkdir(parents=True, exist_ok=False)
    chosen = [c for c in CONVERSATIONS if not args.only or c[0] == args.only]
    if not chosen:
        raise SystemExit(f"Unknown conversation; choose from {[c[0] for c in CONVERSATIONS]}")
    report = {
        "text_model": os.environ.get("TEXT_MODEL"),
        "source_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "jev_ultrafast").iterdir() if p.suffix in {".py", ".js"}
        },
        "conversations": [],
    }
    for name, turns in chosen:
        print(name, flush=True)
        folder = args.folder / name
        report["conversations"].append(run_conversation(name, turns, folder, args.record))
        (args.folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    requests = [r for c in report["conversations"] for r in c["requests"]]
    print(f"{sum(r['passed'] for r in requests)}/{len(requests)} requests passed")


if __name__ == "__main__":
    main()
