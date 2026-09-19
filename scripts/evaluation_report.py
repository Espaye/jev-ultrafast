"""Summarize scripts/conversations.py reports as Markdown.

    uv run python scripts/evaluation_report.py DIR... > docs/evaluation.md
"""

import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Curly quotes survive a Windows console redirect.
reports = [json.loads((Path(d) / "report.json").read_text(encoding="utf-8")) for d in sys.argv[1:]]
hashes = {json.dumps(r["source_hashes"], sort_keys=True) for r in reports}
assert len(hashes) == 1, "Every run must use the same source"
rows = {}
for report in reports:
    for conversation in report["conversations"]:
        for turn, request in enumerate(conversation["requests"]):
            rows.setdefault((conversation["name"], turn), []).append(request)
requests = [r for runs in rows.values() for r in runs]
passed = sum(r["passed"] for r in requests)
conversations = [c for report in reports for c in report["conversations"]]
whole = sum(all(r["passed"] for r in c["requests"]) for c in conversations)


def median(values):
    return statistics.median(values) if values else 0


print("# Evaluation: spoken-style conversations on the real web\n")
runs = f"{len(reports)} run{'s' * (len(reports) > 1)}"
print(f"**{passed}/{len(requests)} requests passed** ({passed / len(requests):.0%}) across {runs} of "
      f"{len(conversations) // len(reports)} conversations; **{whole}/{len(conversations)} conversations** passed "
      f"every request. Median time per request **{median([r['seconds'] for r in requests]):.1f} s**, "
      f"median **{median([r['model_calls'] for r in requests]):g}** Jev decisions per request.\n")
print("Each conversation starts in a fresh tab of the same Chrome profile, on the site a request names or on a "
      "Google search, exactly as the inspector does. Follow-ups continue in that tab. A request passes only when "
      "its check holds on the final page; Jev's own `DONE` is never counted. Requests are fed as the text Chrome's "
      "speech recognition would produce, so this measures browsing, not hearing. Times include model calls, text "
      "generation, page loads and waits. Each request may use at most 40 decisions.\n")
print(f"Text helper: `{reports[0].get('text_model')}`. Operation and element: TypeSafe `jev-latest`. "
      "Source: identical in every run (SHA-256 per file in each `report.json`).\n")
print("| Conversation | Request | Passed | Median time | Median decisions | What the check requires |")
print("| --- | --- | --- | --- | --- | --- |")
for (name, turn), runs in rows.items():
    first = runs[0]
    print(f"| {name if turn == 0 else ''} | “{first['request']}” | {sum(r['passed'] for r in runs)}/{len(runs)} | "
          f"{median([r['seconds'] for r in runs]):.1f} s | {median([r['model_calls'] for r in runs]):g} | "
          f"{first['check']} |")
failures = [(i + 1, name, r) for i, report in enumerate(reports) for c in report["conversations"]
            for r in c["requests"] if not r["passed"] for name in [c["name"]]]
print("\n## Every failure\n")
if not failures:
    print("None.")
for run, name, r in failures:
    actions = " → ".join(r["actions"]) or "no actions"
    detail = f"; {r['error']}" if r["error"] else ""
    print(f"- Run {run}, {name}, “{r['request']}”: ended `{r['status']}`{detail} at `{r['url'][:100]}`. "
          f"Actions: {actions}.")
print("\nReproduce with `uv run --env-file .env python scripts/conversations.py <new-folder>` (paid model calls). "
      "Live sites change, so results vary from day to day.")
