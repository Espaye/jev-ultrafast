"""uv run --env-file .env python examples/run.py --url URL --goal 'A narrow goal'"""

import argparse

from jev_ultrafast import Agent
from jev_ultrafast.console import say

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--goal", action="append", required=True, help="Repeat for an ordered list of goals.")
args = parser.parse_args()

with Agent(args.url, args.goal) as agent:
    for state in agent.run():
        say(f"{state['elapsed_ms']:>5} ms  {len(state['history'])} actions  {state['status']}")
    say(state["page"]["url"])
