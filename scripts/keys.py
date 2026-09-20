"""Keyboard tasks and Back: arrow keys in a game, letters and Enter in a word puzzle, going back a page.

Runs like scripts/conversations.py (fresh tab per conversation, follow-ups in the same tab). Each check reads the
page's own state after the request (the game's score, the puzzle's locked-in rows, the address), never Jev's DONE.

    uv run --env-file .env python scripts/keys.py artifacts/keys/run-1
    uv run --env-file .env python scripts/keys.py artifacts/keys/dev --only 2048

Makes paid model calls. The 2048 board is a local, seeded fixture: public 2048 sites draw on a canvas.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import conversations  # noqa: E402
from conversations import run_request  # noqa: E402

from jev_ultrafast import Agent  # noqa: E402
from jev_ultrafast.console import say  # noqa: E402

conversations.TICKS = 80  # A game needs more moves than a conversation request.
GAME = (ROOT / "scripts" / "fixtures" / "2048.html").as_uri()


def score(browser, _page):
    return browser.evaluate("window.game.score")


def row(n):
    """The letters of the n-th locked-in wordly.org row, or None."""
    def read(browser, _page):
        # .game_rows holds the board; a pop-up copy of the latest guess sits outside it. Letters carry a count digit.
        return browser.evaluate(
            f"[...document.querySelectorAll('.game_rows .Row-locked-in')][{n - 1}]"
            "?.textContent.replace(/[^a-z]/gi, '').toLowerCase() ?? null")
    return read


def comments(_browser, page):
    return "news.ycombinator.com/item?id=" in page["url"]


def front_page(_browser, page):
    return page["url"].rstrip("/") in {"https://news.ycombinator.com", "https://news.ycombinator.com/news"}


# (name, start, [(request, read(browser, page) -> value, passes(value) -> bool, what the check means)])
CONVERSATIONS = [
    ("2048", GAME, [
        ("play 2048 with the arrow keys until the score is at least 100",
         score, lambda v: v >= 100, "the game's own score is at least 100"),
    ]),
    ("wordly", "https://wordly.org/", [
        ("guess the word crane",
         row(1), lambda v: v == "crane", "the first locked-in row is CRANE"),
        ("now guess slate",
         row(2), lambda v: v == "slate", "the second locked-in row is SLATE"),
    ]),
    ("back", "https://news.ycombinator.com/", [
        ("open the comments of the top story",
         comments, bool, "a Hacker News comment page"),
        ("go back to the front page",
         front_page, bool, "the Hacker News front page again"),
    ]),
]


def run_conversation(name, start, turns):
    results = []
    with Agent(start, turns[0][0], web_search=True) as agent:
        if start.startswith("https://wordly.org"):
            # Every run starts as a first visit: a fresh game and the cookie consent dialog. This clears only
            # wordly.org's own data in the test profile.
            agent.browser.call("Storage.clearDataForOrigin", origin="https://wordly.org", storageTypes="all")
            agent.browser.navigate(start)
            agent.state["page"] = agent.observe()
        for i, (request, read, passes, meaning) in enumerate(turns):
            if i:
                agent.new_task(request)
            result = run_request(agent, 0)
            page = agent.browser.observe(screenshot=False)
            value = read(agent.browser, page)
            result.update(request=request, check=meaning, url=page["url"], value=value,
                          # A voice user hears "I got stuck" for a blocked run, even when the page is right.
                          passed=result["status"] == "done" and value is not None and bool(passes(value)),
                          text_values=[c.get("value") for c in agent.state["text_calls"]])
            results.append(result)
            say(f"  {'PASS' if result['passed'] else 'FAIL'} {result['status']:7} {result['seconds']:6.2f}s "
                f"{len(result['actions']):3} actions  {request!r} -> {value!r}")
    return {"name": name, "start": start, "requests": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--only", help="Run one conversation by name")
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
    for name, start, turns in chosen:
        print(name, flush=True)
        report["conversations"].append(run_conversation(name, start, turns))
        (args.folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    requests = [r for c in report["conversations"] for r in c["requests"]]
    print(f"{sum(r['passed'] for r in requests)}/{len(requests)} requests passed")


if __name__ == "__main__":
    main()
