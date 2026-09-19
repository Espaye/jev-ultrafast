"""Ask Jev questions the way a voice user would, and check what it says, not only where it ends up.

Runs like scripts/conversations.py (fresh tab per conversation, follow-ups in the same tab), then checks the
spoken answer independently: a number or time in it must appear on Jev's final page, and where a reference
exists (Open-Meteo for the weather, fixed facts for the Eiffel Tower) it must agree with that too.
A request that only asks for an action must get no answer at all.

    uv run --env-file .env python scripts/answers.py artifacts/answers/run-1
    uv run --env-file .env python scripts/answers.py artifacts/answers/dev --only weather

Makes paid model calls.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from conversations import run_request, site_in  # noqa: E402

from jev_ultrafast import Agent  # noqa: E402
from jev_ultrafast.browser import SEARCH_URL  # noqa: E402

TOLERANCE_C = 3  # Weather sites and Open-Meteo use different stations and update times.


def utrecht_weather():
    """Open-Meteo, read once before the run: the reference Jev never sees."""
    data = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": 52.09, "longitude": 5.12, "current": "temperature_2m",
                "daily": "temperature_2m_max,temperature_2m_min", "timezone": "Europe/Amsterdam"},
        timeout=15,
    ).json()
    return {"now": data["current"]["temperature_2m"],
            "tomorrow": [data["daily"]["temperature_2m_min"][1], data["daily"]["temperature_2m_max"][1]]}


def numbers(text):
    return [int(n) for n in re.findall(r"(?<![\d:])-?\d{1,3}(?![\d:])", text or "")]


def celsius(answer):
    """(as said, in °C) for each number in the answer."""
    fahrenheit = re.search(r"°\s*F|fahrenheit", answer or "", re.I)
    return [(v, round((v - 32) * 5 / 9) if fahrenheit else v) for v in numbers(answer)]


def on_page(value, page):
    text = page["text"] + "\n" + page.get("document", "")  # What the answer helper was given.
    return re.search(rf"(?<!\d){re.escape(str(value))}(?!\d)", text) is not None


def weather_now(page, answer, ref):
    return any(abs(c - ref["now"]) <= TOLERANCE_C and on_page(said, page) for said, c in celsius(answer))


def weather_tomorrow(page, answer, ref):
    low, high = ref["tomorrow"]
    return any(low - TOLERANCE_C <= c <= high + TOLERANCE_C for _, c in celsius(answer))


def clock(text, now):
    at = datetime.datetime.combine(now.date(), datetime.time.fromisoformat(text.zfill(5)))
    return at + datetime.timedelta(days=1) if at < now - datetime.timedelta(hours=12) else at


def departure(page, answer, _ref):
    """The first trip in ns.nl's results that has not left yet: planned time, or planned plus its delay."""
    # ns.nl remembers the last trip searched in this profile; the planned one must be the one asked for.
    if not re.search(r"ns\.nl/reisplanner/.*vertrek=Utrecht.*aankomst=Amsterdam", page["url"]):
        return False
    now = datetime.datetime.now().replace(second=0, microsecond=0)  # This machine runs on Dutch time.
    trips = [
        (clock(planned, now) + datetime.timedelta(minutes=int(delay or 0)), clock(planned, now))
        for planned, delay in re.findall(r"vertrek (\d{1,2}:\d{2})(?: met (\d+) minu)?", page["text"])
    ]
    upcoming = sorted(trip for trip in trips if trip[0] >= now)
    if not upcoming:
        return False
    # The train that really leaves first; a delayed one may leave after the next one on the list.
    leaves, planned = upcoming[0]
    said = {clock(t.replace(".", ":"), now) for t in re.findall(r"\b\d{1,2}[:.]\d{2}\b", answer or "")}
    return planned in said or leaves in said


def price(page, answer, _ref):
    for euros in re.findall(r"(\d{1,4})(?:[.,]\d{2}|,-)?\s*(?:euro|eur\b)|€\s*(\d{1,4})", answer or "", re.I):
        value = euros[0] or euros[1]
        if on_page(value, page):
            return "coolblue.nl" in page["url"]
    return False


def silent(_page, answer, _ref):
    return answer is None


def eiffel_height(_page, answer, _ref):
    return re.search(r"\b(330|324|312|300|1,?083|1,?063)\b", answer or "") is not None


# (name, [(request, check(final_page, answer, reference) -> bool, what the check means)])
CONVERSATIONS = [
    ("weather", [
        ("what's the weather in Utrecht right now",
         weather_now, "a current temperature within 3 °C of Open-Meteo, shown on the page"),
        ("and tomorrow?",
         weather_tomorrow, "a temperature within tomorrow's Open-Meteo range ± 3 °C"),
    ]),
    ("ns", [
        ("go to ns.nl and tell me when the next train from Utrecht Centraal to Amsterdam Centraal leaves",
         departure, "Utrecht → Amsterdam planned on ns.nl; the train that really leaves next, delays included"),
    ]),
    ("coolblue", [
        ("go to coolblue.nl and search for the Nintendo Switch 2, how much does it cost?",
         price, "a euro price shown on coolblue.nl"),
    ]),
    ("eiffel", [
        ("find the Wikipedia article about the Eiffel Tower",
         silent, "no spoken answer: the request is an action"),
        ("how tall is it?",
         eiffel_height, "its height: 330 m (or 300/312/324 m, 1,083 ft)"),
    ]),
]


def run_conversation(name, turns, reference):
    first = turns[0][0]
    start = site_in(first) or SEARCH_URL
    results = []
    with Agent(start, first, web_search=True) as agent:
        for i, (request, check, meaning) in enumerate(turns):
            if i:
                agent.new_task(request, site_in(request))
            result = run_request(agent, 0)
            page = agent.browser.observe(screenshot=False)
            page["document"] = agent.browser.document_text()
            answer = agent.state.get("answer")
            result.update(
                request=request, check=meaning, url=page["url"], answer=answer,
                checked_at=datetime.datetime.now().strftime("%H:%M:%S"), page_text=page["text"][:3000],
                answer_error=agent.state.get("answer_error"),
                passed=result["status"] == "done" and bool(check(page, answer, reference)),
            )
            results.append(result)
            print(f"  {'PASS' if result['passed'] else 'FAIL'} {result['status']:7} {result['seconds']:6.2f}s  "
                  f"{request!r}\n      -> {page['url'][:90]}\n      says: {answer!r}", flush=True)
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
    reference = utrecht_weather()
    report = {
        "text_model": os.environ.get("TEXT_MODEL"),
        "answer_model": os.environ.get("ANSWER_MODEL") or os.environ.get("TEXT_MODEL"),
        "reference": {"open_meteo_utrecht": reference},
        "source_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "jev_ultrafast").iterdir() if p.suffix in {".py", ".js"}
        },
        "conversations": [],
    }
    print(f"Open-Meteo Utrecht: now {reference['now']} °C, tomorrow {reference['tomorrow']} °C", flush=True)
    for name, turns in chosen:
        print(name, flush=True)
        report["conversations"].append(run_conversation(name, turns, reference))
        (args.folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    requests = [r for c in report["conversations"] for r in c["requests"]]
    print(f"{sum(r['passed'] for r in requests)}/{len(requests)} requests passed")


if __name__ == "__main__":
    main()
