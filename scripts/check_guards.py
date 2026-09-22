"""Local-browser freshness/execution regressions. No model calls or external websites."""

from pathlib import Path
from urllib.parse import quote

from jev_ultrafast.agent import GO_BACK, KEY_ACTIONS, TYPE_KEYS
from jev_ultrafast.browser import BUILDING, Browser, StalePage

ROOT = Path(__file__).resolve().parents[1]

HTML = """<!doctype html><title>Guard checks</title>
<style>body{margin:30px}button{width:180px;height:50px}label{display:block}#outside{position:absolute;top:3000px}</style>
<p id="context">Cart total: $10</p>
<button id="target" onclick="window.clicks=(window.clicks||0)+1">Continue</button>
<label>City<input id="field" value="Zurich"></label>
<label><input id="toggle" type="checkbox">Refundable</label>
<select aria-label="Category"><option>All</option><option>Design</option></select>
<p id="outside">Unrelated offscreen text</p>"""


def main():
    browser = Browser("data:text/html," + quote(HTML))
    passed = []
    try:
        page = browser.observe(screenshot=False)
        action = next(a for a in page["actions"] if a["label"] == "Continue")
        browser.evaluate("document.querySelector('#target').style.transform='translateX(200px)'")
        assert browser.fresh(page), "Movement should use fresh geometry, not another model call"
        browser.act(action, page)
        assert browser.evaluate("window.clicks") == 1
        passed.append("moving target clicked at its current location")

        browser.evaluate("document.querySelector('#outside').textContent='Updated outside the viewport'")
        assert browser.fresh(page)
        passed.append("unrelated offscreen text does not invalidate")

        mutations = {
            "visible context": "document.querySelector('#context').textContent='Cart total: $100'",
            "accessible label": "document.querySelector('#target').setAttribute('aria-label','Delete account')",
            "field property": "document.querySelector('#field').value='London'",
            "checkbox property": "document.querySelector('#toggle').checked=true",
            "disabled target": "document.querySelector('#target').disabled=true",
            "read-only field": "document.querySelector('#field').readOnly=true",
            "hidden target": "document.querySelector('#target').style.display='none'",
            "replaced node": "document.querySelector('#target').outerHTML=document.querySelector('#target').outerHTML",
            "dropdown option": "document.querySelector('select').options[1].text='Coastal'",
        }
        for label, expression in mutations.items():
            browser.evaluate("document.querySelector('#target').style.display='block'; "
                             "document.querySelector('#target').disabled=false")
            page = browser.observe(screenshot=False)
            browser.evaluate(expression)
            assert not browser.fresh(page), label
            passed.append(label + " invalidates")

        browser.evaluate("document.querySelector('#target').disabled=false; "
                         "document.querySelector('#target').style.display='block'")
        page = browser.observe(screenshot=False)
        action = next(a for a in page["actions"] if a["label"] == "Delete account")
        # A textless overlay leaves the target's own guard intact, so input's hit test must block the click.
        # Observation shares that hit test: covered controls drop out, so the page as a whole is no longer fresh.
        browser.evaluate("const cover=document.createElement('div'); "
                         "cover.style.cssText='position:fixed;inset:0;z-index:9999;background:white'; "
                         "document.body.append(cover)")
        assert browser.fresh(page, action)
        assert not browser.fresh(page)
        assert not any(a["label"] == "Delete account" for a in browser.observe(screenshot=False)["actions"])
        try:
            browser.act(action, page)
        except (RuntimeError, StalePage):
            pass
        else:
            raise AssertionError("Covered target was clicked")
        assert browser.evaluate("window.clicks") == 1
        passed.append("overlay blocked before input")

        browser.evaluate("document.body.innerHTML=" + repr("""
          <form><p id="price">Total $10</p>
          <button type="button" id="buy">Buy</button>
          <label>Search <input id="query" role="combobox" aria-controls="suggestions"></label>
          <div role="listbox" id="suggestions"></div>
          <label><input id="check" type="checkbox">Enabled</label>
          <label><input id="radio" type="radio">Choice</label>
          <input id="readonly" aria-label="Read only" readonly>
          <input id="secret" type="password" value="never expose this">
          <button id="off" disabled>Disabled</button>
          <select id="category" aria-label="Category">
            <option>All</option><option>Design</option><option disabled>Unavailable</option>
          </select></form><aside id="unrelated">News</aside>
        """))
        page = browser.observe(screenshot=False)
        buy = next(a for a in page["actions"] if a["label"] == "Buy")
        browser.evaluate("document.querySelector('#unrelated').textContent='New unrelated news'")
        assert browser.fresh(page, buy)
        assert not browser.fresh(page)
        passed.append("click guard accepts unrelated visible updates; terminal guard rejects them")
        for label, expression in {
            "nearby price": "document.querySelector('#price').textContent='Total $100'",
            "form value": "document.querySelector('#query').value='changed'",
            "form toggle": "document.querySelector('#check').checked=true",
            "target replacement": "document.querySelector('#buy').outerHTML=document.querySelector('#buy').outerHTML",
        }.items():
            page = browser.observe(screenshot=False)
            buy = next(a for a in page["actions"] if a["label"] == "Buy")
            browser.evaluate(expression)
            assert not browser.fresh(page, buy), label
            passed.append(label + " invalidates action-specific guard")

        page = browser.observe(screenshot=False)
        actions = page["actions"]
        for role in ("checkbox", "radio"):
            assert {a["kind"] for a in actions if a.get("role") == role} == {"click"}
        assert {a["kind"] for a in actions if a["label"] == "Read only"} == {"click"}
        assert not any(a["label"] == "Disabled" or a.get("value") == "never expose this" for a in actions)
        assert [a["value"] for a in actions if a["kind"] == "select"] == ["Design"]
        passed.append("native controls expose only supported operations and safe values")

        select = next(a for a in actions if a["kind"] == "select")
        browser.act(select, page)
        assert browser.evaluate("document.querySelector('#category').value") == "Design"
        passed.append("native dropdown selects an observed option")

        browser.evaluate("document.querySelector('#query').addEventListener('input',()=>setTimeout(()=>{"
                         "document.querySelector('#suggestions').innerHTML='<div role=option>Generated</div>'"
                         "},60))")
        page = browser.observe(screenshot=False)
        field = next(a for a in page["actions"] if a["kind"] == "fill")
        browser.act(field, page, text="Generated")
        page = browser.observe(screenshot=False)
        value = browser.evaluate("document.querySelector('#query').value")
        assert value == "Generated", repr(value)
        assert any(a.get("role") == "option" for a in page["actions"])
        passed.append("real text input waits for asynchronous combobox suggestions")

        browser.call("Page.navigate", url="about:blank")
        assert not browser.fresh(page, field)
        passed.append("navigation invalidates the old document")

        browser.navigate("data:text/html," + quote(
            "<div class=active id=timer>2:00</div><label>Country <input id=answer></label>"))
        page = browser.observe(screenshot=False)
        answer = next(a for a in page["actions"] if a["kind"] == "fill")
        browser.evaluate("document.querySelector('#timer').textContent='1:59'")
        assert browser.fresh(page), "an active countdown tick should not stale a terminal decision"
        assert browser.fresh(page, answer), "an active countdown tick should not stale its textbox"
        browser.evaluate("document.querySelector('label').firstChild.textContent='Capital '")
        assert not browser.fresh(page), "ordinary text changes must still invalidate the page"
        passed.append("active countdown ticks do not stale decisions; other visible text still does")

        browser.navigate("data:text/html," + quote(
            "<title>Keys</title><p>Type here</p><script>window.keys=[];"
            "addEventListener('keydown',e=>keys.push(e.key));</script>"))
        page = browser.observe(screenshot=False)
        for key in ("ArrowLeft", "Enter"):
            browser.act(next(a for a in KEY_ACTIONS if a["key"] == key), page)
            page = browser.observe(screenshot=False)
        browser.act(TYPE_KEYS, page, text="crane")
        assert browser.evaluate("window.keys.join()") == "ArrowLeft,Enter,c,r,a,n,e"
        for invalid in ({**KEY_ACTIONS[0], "key": "F5"}, ):
            try:
                browser.act(invalid, browser.observe(screenshot=False))
            except ValueError:
                pass
            else:
                raise AssertionError("A key outside the fixed set was sent")
        passed.append("key presses and typed letters reach a page that listens for keys; other keys are refused")

        # A board, a rejected field and a closed day say what they mean in colour alone. The characters
        # already reached the text; without their state Jev reads a board it cannot score.
        browser.navigate("data:text/html," + quote(
            "<title>Only colour</title><style>.tile{display:inline-block;width:40px;height:40px}</style>"
            "<div class=row><span class='tile correct'>C</span>"
            "<span class='tile letter-elsewhere'>R</span><span class='tile absent'>N</span></div>"
            "<p class=error>Postcode not recognised</p>"
            "<div class=card><span data-state=unavailable>14 March</span></div>"
            "<p class='wrapper container'>Plain paragraph</p>"
            "<div class=row-locked-in><span class=tile>U</span></div>"))
        text = browser.observe(screenshot=False)["text"]
        for marked in ("C (correct)", "R (elsewhere)", "N (absent)",
                       "Postcode not recognised (error)", "14 March (unavailable)"):
            assert marked in text, (marked, text)
        assert "Plain paragraph" in text and "Plain paragraph (" not in text, text
        # A tile mid-flip has no colour of its own; its row's "locked" must not stand in for one.
        assert "U (" not in text, text
        passed.append("state carried only by colour reaches the text; layout classes do not")

        # Google's AI Mode button carries its own <style>; its name was a line of CSS on every Google page.
        browser.navigate("data:text/html," + quote(
            "<title>Styled</title><button><style>.mode{display:none}</style>AI Mode</button>"))
        labels = [a["label"] for a in browser.observe(screenshot=False)["actions"] if a["kind"] == "click"]
        assert labels == ["AI Mode"], labels
        passed.append("a control's own stylesheet is not part of its name")

        # GitHub's repository page replaces its placeholders over a second; its Releases link comes last. Timed
        # with requestAnimationFrame: Chrome throttles timers in a background tab, not frames.
        browser.navigate("data:text/html," + quote(
            "<title>Filling in</title><p class=hide-skeleton>Watch page</p><div aria-busy=true hidden>Menu</div>"
            "<div id=side>" + "<div class=Skeleton style='width:90px;height:9px'></div>" * 3 + "</div><script>"
            "const t0=performance.now(), step=()=>{const t=performance.now()-t0, side=document.querySelector('#side');"
            "if (t>100 && side.children.length===3) side.firstChild.remove();"
            "if (t>700) { side.innerHTML='<a href=#releases>Releases</a>'; return; } requestAnimationFrame(step); };"
            "requestAnimationFrame(step);</script>"))
        labels = [a["label"] for a in browser.observe(screenshot=False)["actions"]]
        assert "Releases" in labels, labels
        assert browser.evaluate(BUILDING) == [False, 0]  # Hidden busy marks and real content do not count.
        passed.append("a page replacing its placeholders is read once they are gone; hidden busy marks do not count")

        browser.navigate((ROOT / "scripts" / "fixtures" / "2048.html").as_uri())
        page = browser.observe(screenshot=False)
        before = page["text"]
        browser.act(next(a for a in KEY_ACTIONS if a["key"] == "ArrowUp"), page)
        page = browser.observe(screenshot=False)
        assert browser.evaluate("window.game.moves") == 1 and page["text"] != before
        passed.append("an arrow key moves the 2048 fixture and the new board is observed")

        assert browser.can_go_back()
        browser.act(GO_BACK, browser.observe(screenshot=False))
        assert browser.observe(screenshot=False)["url"].startswith("data:text/html")
        passed.append("Back returns to the previous page")
    finally:
        browser.close()
    print("\n".join(passed))
    print(f"PASS: {len(passed)} browser guard checks; no model calls")


if __name__ == "__main__":
    main()
