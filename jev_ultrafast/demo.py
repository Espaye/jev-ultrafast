"""Loopback-only inspector for the Jev browser agent."""

import atexit
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .agent import Agent
from .browser import BrowserGone
from .questions import MAX_STEPS

ROOT = Path(__file__).parent
PORT = int(os.environ.get("TYPESAFE_DEMO_PORT", "8766"))
ORIGIN = f"http://127.0.0.1:{PORT}"
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
AGENT = None
# Steering test: how the decoy article in the reading room is worded (see fixture.html).
DECOYS = {"none", "neutral", "suggestive", "verdict", "instruction"}
# Real-web scenarios where each new request continues in the same tab.
CONVERSATION = {"search", "custom"}


def load_environment():
    path = Path.cwd() / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


def response_state():
    state = AGENT.snapshot() if AGENT else {"page": None, "status": "idle", "history": [], "decision": None}
    return {**state, "text_model": os.environ.get("TEXT_MODEL", "deepseek-chat"), "max_steps": MAX_STEPS}


def close_browser():
    global AGENT
    agent, AGENT = AGENT, None
    if agent:
        agent.close()


def custom_url(value):
    value = str(value or "").strip()
    if value and "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    try:
        parsed.port  # Rejects malformed hosts such as "javascript:alert(1)" after the https:// prefix.
    except ValueError:
        parsed = None
    if not parsed or parsed.scheme not in {"http", "https"} or not parsed.hostname or len(value) > 2000:
        raise ValueError("Enter a website address, e.g. https://example.com")
    return value


def scenario_url(scenario, body):
    if scenario == "flights":
        return "https://www.google.com/travel/flights?hl=en"
    if scenario == "search":
        # Tasks that name no website start here; Jev cannot use the address bar.
        return "https://www.google.com/?hl=en"
    if scenario in {"travel", "research"}:
        return f"{ORIGIN}/fixture.html?scenario={scenario}"
    if scenario == "steering":
        decoy = body.get("decoy", "neutral")
        if decoy not in DECOYS:
            raise ValueError("Unknown decoy wording")
        return f"{ORIGIN}/fixture.html?scenario=research&decoy={decoy}"
    if scenario == "custom":
        return custom_url(body.get("url"))
    raise ValueError("Unknown demo scenario")


def task_goal(body):
    goal = body.get("goal", "").strip()
    if not goal or len(goal) > 2000:
        raise ValueError("Enter 1–2,000 characters")
    return goal


def start(scenario, url, goal, body):
    global AGENT
    close_browser()
    AGENT = Agent(
        url,
        goal,
        screenshots=True,
        record_dir=Path.cwd() / "artifacts" / "frames" if body.get("record") else None,
        # Real-web conversations may need another site; fixtures and the Flights demo stay where they are.
        web_search=scenario in CONVERSATION,
    )
    AGENT.state["scenario"] = scenario
    AGENT.state["decoy"] = body.get("decoy") if scenario == "steering" else None


def command(name, body):
    if name == "reset":
        scenario = body.get("scenario", "flights")
        start(scenario, scenario_url(scenario, body), task_goal(body), body)
    elif name == "continue":
        # A follow-up request continues in the same tab, from the page the last request ended on.
        goal = task_goal(body)
        url = custom_url(body["url"]) if body.get("url") else None
        try:
            if AGENT is None or AGENT.state.get("scenario") not in CONVERSATION:
                raise BrowserGone("No conversation to continue")
            AGENT.new_task(goal, url)
        except BrowserGone:
            # Nothing to continue, or the user closed Jev's tab: start the request in a fresh one.
            start("custom" if url else "search", url or scenario_url("search", body), goal, body)
    else:
        if AGENT is None:
            raise ValueError("Start a demo first")
        AGENT.command(name, body)
    return response_state()


class Handler(BaseHTTPRequestHandler):
    def send(self, status, content, mime="application/json"):
        content = content if isinstance(content, bytes) else content.encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.headers.get("Host") != f"127.0.0.1:{PORT}":
            return self.send(403, "Forbidden", "text/plain")
        path = urlparse(self.path).path
        if path == "/api/state":
            with LOCK:
                return self.send(200, json.dumps(response_state()))
        if path == "/demo.mp4":
            video = ROOT.parent / "docs" / "demo.mp4"
            if video.exists():
                return self.send(200, video.read_bytes(), "video/mp4")
        files = {
            "/": ("index.html", "text/html"),
            "/app.js": ("app.js", "text/javascript"),
            "/style.css": ("style.css", "text/css"),
            "/fixture.html": ("fixture.html", "text/html"),
        }
        if path not in files:
            return self.send(404, "Not found", "text/plain")
        name, mime = files[path]
        content = (ROOT / "static" / name).read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
        self.send(200, content, mime + "; charset=utf-8")

    def do_POST(self):
        if (
            self.headers.get("Host") != f"127.0.0.1:{PORT}"
            or self.headers.get("X-Demo-Token") != TOKEN
            or self.headers.get("Origin") not in (None, ORIGIN)
        ):
            return self.send(403, json.dumps({"error": "Local demo requests only"}))
        if not LOCK.acquire(blocking=False):
            return self.send(409, json.dumps({"error": "A browser step is already running"}))
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 8192:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length))
            result = command(self.path.removeprefix("/api/"), body)
            self.send(200, json.dumps(result))
        except (ValueError, RuntimeError, TimeoutError) as error:
            self.send(400, json.dumps({"error": str(error)}))
        except Exception:
            self.send(500, json.dumps({"error": "Local demo failed; no automatic retry. Click Start demo to recover."}))
        finally:
            LOCK.release()

    def log_message(self, *_args):
        pass


def main():
    load_environment()
    atexit.register(close_browser)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Jev Ultrafast: {ORIGIN}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
