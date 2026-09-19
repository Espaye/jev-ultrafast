"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import hashlib
import json
import sys
import time
from pathlib import Path

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

# Atomically read visible content and controls, preserving actual DOM node identity.
READ_STATE = Path(__file__).with_name("snapshot.js").read_text(encoding="utf-8")
MARKER = f"(() => {{ const state={READ_STATE}; return state?.marker ?? null; }})()"
SEARCH_URL = "https://www.google.com/?hl=en"
# Counts added/removed elements. Timing stays in Python: Chrome throttles timers in background tabs.
MUTATIONS = """(() => {
  if (!window.__jevMutations) {
    window.__jevMutations = {count: 0};
    new MutationObserver(records => { window.__jevMutations.count += records.length; })
      .observe(document.documentElement, {childList: true, subtree: true});
  }
  return window.__jevMutations.count;
})()"""


class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


class BrowserGone(RuntimeError):
    """The owned tab was closed or its CDP session detached; only a reset recovers."""


def session_cdp(method, session, **params):
    try:
        return cdp(method, session_id=session, **params)
    except RuntimeError as error:
        message = str(error).lower()
        if "session with given id not found" in message or "no session with given id" in message:
            raise BrowserGone(
                "The agent's browser tab was closed or disconnected. Click Start demo to open a fresh one."
            ) from error
        raise


class Browser:
    def __init__(self, url):
        ensure_daemon()
        self.attach(cdp("Target.createTarget", url="about:blank", background=True)["targetId"])
        self.navigate(url)

    def navigate(self, url):
        self.after_input = None
        self.call("Page.navigate", url=url)
        self.wait_for_load()

    def attach(self, target):
        self.target = target
        self.session = cdp("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
        # Keep rAF/menus rendering in an owned background tab, without activating the user's Chrome tab.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)

    def wait_for_load(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if self.evaluate("document.readyState") == "complete":
                    break
            except StalePage:
                pass  # A fresh tab can still be swapping documents.
            time.sleep(0.02)
        self.settle()

    def settle(self):
        """Apps such as YouTube build the page after "load": wait for 150 ms without new elements, at most 1.5 s."""
        deadline = time.monotonic() + 1.5
        last, quiet_since = None, time.monotonic()
        while time.monotonic() < deadline:
            try:
                count = self.evaluate(MUTATIONS)
            except StalePage:
                return  # Still navigating; observe() retries until the new document can be read.
            now = time.monotonic()
            if count != last:
                last, quiet_since = count, now
            elif now - quiet_since >= 0.15:
                return
            time.sleep(0.03)

    def left_page(self):
        """True when the last click loaded another document (Google → YouTube) or changed the address in the same
        document (client-side routing, as on nos.nl). Either way the new page may still be building."""
        try:
            return self.evaluate("[performance.timeOrigin, location.href]") != self.clicked_page
        except StalePage:
            return True

    def follow_new_tab(self):
        """A link that opens a new tab (target=_blank, Google's "open in new window") moves the run there."""
        opened = [
            t["targetId"]
            for t in cdp("Target.getTargets")["targetInfos"]
            if t.get("openerId") == self.target and t["type"] == "page"
        ]
        if not opened:
            return False
        old = self.target
        self.attach(opened[-1])
        for extra in opened[:-1]:
            cdp("Target.closeTarget", targetId=extra)
        try:
            cdp("Target.closeTarget", targetId=old)
        except RuntimeError:
            pass  # The opener may already be gone.
        self.wait_for_load()
        return True

    def call(self, method, **params):
        return session_cdp(method, self.session, **params)

    def evaluate(self, expression):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def observe(self, screenshot=True):
        if getattr(self, "after_input", None):
            action, self.after_input = self.after_input, None
            # This is read-only and happens after execution was logged, even if navigation interrupts it.
            try:
                self.call(
                    "Runtime.evaluate",
                    expression="""(action => new Promise(resolve => {
                      const field=window.__jevFast?.nodes.get(action.node);
                      const autocomplete=action.kind==='fill' && field?.getAttribute('role')==='combobox';
                      let frames=0, stopped=false;
                      const finish=()=>{stopped=true;resolve()};
                      setTimeout(finish,autocomplete ? 200 : 50);
                      const ready=()=>{
                        if (stopped) return;
                        const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
                          .split(/\\s+/).filter(Boolean);
                        const roots=ids.length ? ids.map(id=>document.getElementById(id)).filter(Boolean) : [document];
                        const options=roots.flatMap(root=>[...root.querySelectorAll('[role="option"]')]);
                        if (++frames>=2 && (!autocomplete || options.some(e=>{
                          const r=e.getBoundingClientRect();
                          return r.width && r.height && r.bottom>0 && r.top<innerHeight &&
                            e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
                        }))) finish();
                        else requestAnimationFrame(ready);
                      };
                      requestAnimationFrame(ready);
                    }))(""" + json.dumps(action) + ")",
                    awaitPromise=True,
                    returnByValue=True,
                )
            except RuntimeError:
                pass
            if action["kind"] == "click" and not self.follow_new_tab() and self.left_page():
                self.wait_for_load()
        # A cross-site navigation (Google → YouTube) can take seconds to commit.
        deadline = time.monotonic() + 3
        while True:
            try:
                return browser_operation(
                    {"operation": "observe", "session": self.session, "screenshot": screenshot}
                )
            except StalePage:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.02)

    def fresh(self, page, action=None):
        if action is not None and action["kind"] in {"click", "select", "place"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.evaluate(
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()"
            )
            return current == [page["page_key"], page["guards"].get(str(node))]
        return self.evaluate(MARKER) == page["marker"]

    def screenshot(self):
        """The viewport as JPEG base64, for the map helper that has to see the page. A background tab sometimes
        produces no frame; a read is safe to repeat, and captureBeyondViewport forces a fresh composite."""
        for attempt in range(3):
            try:
                return self.call(
                    "Page.captureScreenshot", format="jpeg", quality=80, captureBeyondViewport=attempt > 0
                )["data"]
            except TimeoutError:
                if attempt == 2:
                    raise StalePage("The tab produced no screenshot for the map helper. Observe again.") from None

    def act(self, action, page, text=None, place=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            # Until the document has loaded and stopped building, not a fixed sleep.
            self.wait_for_load()
        if action["kind"] == "search":
            # A fixed address owned by code; the model never supplies a URL.
            self.navigate(SEARCH_URL)
            return {"executed": action["id"]}
        # The document and address the click started on; marker = [performance.timeOrigin, location.href, ...].
        self.clicked_page = page.get("marker", [None, None])[:2]
        result = browser_operation(
            {"operation": "act", "session": self.session, "action": action, "text": text, "place": place}
        )
        self.after_input = action if action["kind"] != "wait" else None
        return result

    def close(self):
        target, self.target = self.target, None
        if target:
            try:
                cdp("Target.closeTarget", targetId=target)
            except RuntimeError:
                pass  # Already closed by the user or Chrome; nothing left to clean up.


def fingerprint(state):
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


# Runs a map helper from snapshot.js on the observed map node: mapPoint (pixel for a place) or mapPan (drag).
MAP = """(({node, lat, lng}, method) => {
  const c=window.__jevFast, e=c?.nodes.get(node);
  return e?.isConnected ? c[method](e, lat, lng) : null;
})"""


def place_on_map(call, evaluate, action, place):
    """Click a latitude/longitude on an observed tile map. The pixel comes from the tiles, never from the model.
    A place under an overlay or off screen is first dragged into open map, the way a person pans."""
    if type(action["node"]) is not int:
        raise ValueError("Invalid observed node")
    args = json.dumps({"node": action["node"], "lat": place["lat"], "lng": place["lng"]})

    def locate(method):
        return evaluate(f"{MAP}({args}, {json.dumps(method)})")

    point = locate("mapPoint")
    if point is None:
        raise StalePage("The map is gone or has no tiles. Observe again.")
    if not point["open"]:
        pan = locate("mapPan")
        if pan is None:
            raise StalePage("No open part of the map to move the place into. Observe again.")
        (x, y), (tx, ty) = (pan["from"]["x"], pan["from"]["y"]), (pan["to"]["x"], pan["to"]["y"])
        call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        # Slow, even steps: a fast flick makes maps coast on after release (inertia).
        for step in range(1, 13):
            time.sleep(0.05)
            call("Input.dispatchMouseEvent", type="mouseMoved", x=x + (tx - x) * step / 12,
                 y=y + (ty - y) * step / 12, button="left", buttons=1)
        call("Input.dispatchMouseEvent", type="mouseReleased", x=tx, y=ty, button="left", clickCount=1)
        # Wait until the tiles stop moving before projecting again.
        last, deadline = None, time.monotonic() + 2
        while time.monotonic() < deadline:
            view = evaluate(f"(({{node}}) => window.__jevFast.mapView(window.__jevFast.nodes.get(node)))({args})")
            if view is not None and view == last:
                break
            last = view
            time.sleep(0.08)
        point = locate("mapPoint")
        if point is None or not point["open"]:
            raise StalePage("The place is still covered after moving the map. Observe again.")
    for event in ("mousePressed", "mouseReleased"):
        call("Input.dispatchMouseEvent", type=event, x=point["x"], y=point["y"], button="left", clickCount=1)


def browser_operation(request):
    operation = request["operation"]
    session = request["session"]

    def call(method, **params):
        return session_cdp(method, session, **params)

    def evaluate(expression):
        result = call("Runtime.evaluate", expression=expression, returnByValue=True)
        if result.get("exceptionDetails"):
            if operation == "act" and request["action"]["kind"] == "select":
                raise RuntimeError("Dropdown execution was interrupted; inspect before retrying.")
            raise StalePage("Document changed during evaluation")
        return result.get("result", {}).get("value")

    if operation == "act":
        action = request["action"]
        kind = action["kind"]
        if kind == "scroll":
            call("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=650, deltaX=0, deltaY=action["delta"])
        elif kind == "place":
            place_on_map(call, evaluate, action, request["place"])
        elif kind != "wait":
            if type(action["node"]) is not int:
                raise ValueError("Invalid observed node")
            # Code-owned node IDs refer to actual observed elements, never model-generated selectors.
            target = evaluate("""(action => {
              const e=window.__jevFast?.nodes.get(action.node);
              if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
                  !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
              if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
              const point=window.__jevFast.point(e);
              if (!point) return null;
              if (action.kind==='select') {
                if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
                    !o.disabled && !o.closest('optgroup[disabled]'))) return null;
                e.value=action.value;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
              }
              return point;
            })(""" + json.dumps(action) + ")")
            if target is None:
                if kind == "select":
                    raise RuntimeError("Dropdown execution was not confirmed; inspect before retrying.")
                raise StalePage("Target changed or is covered. Observe again.")
            if kind != "select":
                x, y = target["x"], target["y"]
                for event in ("mousePressed", "mouseReleased"):
                    call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)
                if kind == "fill":
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyDown",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                        commands=["selectAll"],
                    )
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyUp",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                    )
                    call("Input.insertText", text=request["text"])
        return {"executed": action["id"]}

    info = evaluate(READ_STATE)
    if info is None:
        raise StalePage("Document is navigating")
    info["fingerprint"] = fingerprint(info)
    if request.get("screenshot", True):
        # A background tab sometimes never produces a frame. Screenshots only feed the inspector, so skip it.
        try:
            info["screenshot"] = call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
        except TimeoutError:
            info["screenshot"] = None
    return info
