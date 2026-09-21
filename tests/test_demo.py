import pytest

from jev_ultrafast.demo import ORIGIN, custom_url, scenario_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("example.com", "https://example.com"),
        (" https://news.ycombinator.com/ ", "https://news.ycombinator.com/"),
        ("http://localhost:3000/a?b=1", "http://localhost:3000/a?b=1"),
    ],
)
def test_custom_url_accepts_web_addresses(value, expected):
    assert custom_url(value) == expected


@pytest.mark.parametrize(
    "value", ["", None, "javascript:alert(1)", "file:///C:/x", "chrome://settings", "https://", "https://a:b"]
)
def test_custom_url_rejects_everything_else(value):
    with pytest.raises(ValueError):
        custom_url(value)


def test_search_starts_on_a_search_engine():
    assert scenario_url("search", {"url": "x.com"}) == "https://www.google.com/?hl=en"


def test_steering_opens_the_reading_room_with_a_known_decoy():
    assert scenario_url("steering", {"decoy": "verdict"}) == f"{ORIGIN}/fixture.html?scenario=research&decoy=verdict"
    with pytest.raises(ValueError):
        scenario_url("steering", {"decoy": "<script>"})
    with pytest.raises(ValueError):
        scenario_url("unknown", {})


def test_follow_up_without_a_conversation_starts_a_web_search(monkeypatch):
    import jev_ultrafast.demo as demo

    started = []
    monkeypatch.setattr(demo, "AGENT", None)
    monkeypatch.setattr(demo, "start", lambda *args: started.append(args[:3]))
    monkeypatch.setattr(demo, "response_state", lambda: {})
    demo.command("continue", {"goal": "open the wikipedia article about 9/11"})
    assert started == [("search", "https://www.google.com/?hl=en", "open the wikipedia article about 9/11")]


def test_the_inspector_takes_the_stop_before_the_answer(monkeypatch):
    """Its clock stops when the run does; app.js then asks for the answer as a request of its own."""
    from unittest.mock import Mock

    import jev_ultrafast.demo as demo

    made = []
    monkeypatch.setattr(demo, "AGENT", None)
    monkeypatch.setattr(demo, "close_browser", lambda: None)
    monkeypatch.setattr(demo, "Agent", lambda *args, **kwargs: made.append(kwargs) or Mock(state={}))
    demo.start("search", "https://www.google.com/?hl=en", "find it", {})
    assert made[0]["answer_later"] is True
