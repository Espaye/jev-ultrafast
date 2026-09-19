"""Offline contracts for a dynamic operation/target policy. No paid APIs."""

import json
import time
from copy import deepcopy
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import model
from jev_ultrafast.browser import StalePage, browser_operation, fingerprint


def page():
    state = {
        "url": "https://example.test/",
        "title": "Search",
        "text": "Search",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "click", "label": "Open Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e3", "kind": "click", "label": "Go", "role": "button", "value": "", "node": 20},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    state["fingerprint"] = fingerprint(state)
    return state


def choice(ids, selected):
    return {"choice": selected, "confidence": 1.0, "probabilities": {i: float(i == selected) for i in ids}}


def decision(action="e1"):
    return {
        "choice": action,
        "operation": "TYPE_TEXT",
        "target": "1",
        "confidence": 1.0,
        "probabilities": {action: 1.0},
        "latency_ms": 10,
        "usage": {},
    }


@pytest.mark.parametrize("mutation", ["unknown", "nan", "missing", "negative", "non_max", "confidence"])
def test_invalid_choice_is_rejected(mutation):
    a = choice(["a", "b"], "a")
    if mutation == "unknown":
        a["choice"] = "invented"
    elif mutation == "nan":
        a["probabilities"]["a"] = float("nan")
    elif mutation == "missing":
        del a["probabilities"]["b"]
    elif mutation == "negative":
        a["probabilities"]["b"] = -1
    elif mutation == "non_max":
        a["choice"] = "b"
    else:
        a["confidence"] = 5
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.validate_choice(a, {"a", "b"})


def test_one_index_per_node_with_operation_specific_targets():
    elements, targets, controls = model.action_space(page()["actions"])
    assert len(elements) == 2
    assert elements[0]["operations"] == ["TYPE_TEXT", "CLICK"]
    assert targets["TYPE_TEXT"]["1"]["id"] == "e1"
    assert targets["CLICK"]["1"]["id"] == "e2"
    assert targets["CLICK"]["2"]["id"] == "e3"
    assert "WAIT" in controls


def test_all_heads_are_one_request_and_only_matching_head_executes(monkeypatch):
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1"], "1"),
                "click_target": {"choice": "invented"},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Find a book", [])
    assert len(calls) == 1
    assert d["operation"] == "TYPE_TEXT" and d["target"] == "1" and d["choice"] == "e1"
    assert set(calls[0]["questions"]) == {"operation", "click_target", "type_text_target"}


def test_click_cannot_consume_a_text_target(monkeypatch):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "type_text_target": choice(["1"], "1"),
                "click_target": choice(["1", "2", "999"], "999"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.choose(page(), "Find a book", [])


def test_target_head_receives_control_state_and_full_next_step_rules(monkeypatch):
    p = page()
    p["actions"].insert(0, {
        "id": "toggle", "kind": "click", "label": "Free cancellation", "node": 30,
        "role": "checkbox", "checked": "true", "selected": False,
    })

    def post(_url, _key, body):
        questions = body["questions"]
        target = questions["click_target"]
        assert target["criteria"]["1"]["checked"] == "true"
        assert target["criteria"]["1"]["selected"] is False
        assert questions["operation"]["instructions"]["rules"] in target["instructions"]["rules"]
        return {
            "model": "test",
            "answers": {
                "operation": choice(questions["operation"]["criteria"], "CLICK"),
                "click_target": choice(target["criteria"], "3"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(p, "Search with free cancellation", [])
    assert d["choice"] == "e3"


def test_quoted_task_text_still_uses_the_llm(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    context = model.field_context('Fly from "Zurich" to London', page()["actions"][0], page(), [])
    assert model.field_text(context)[0] == "Zurich"
    assert post.call_count == 1
    sent = json.loads(post.call_args.args[2]["messages"][1]["content"])
    assert sent["goal"] == 'Fly from "Zurich" to London'


def test_missing_text_credential_stops_before_guessing(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TEXT_MODEL_API_KEY"):
        model.field_text({"goal": 'Enter "Zurich"'})


@pytest.fixture
def runner():
    a = loop.Agent.__new__(loop.Agent)
    a.screenshots = False
    a.pending_text = None
    p = page()
    a.state = {
        "browser": Mock(fresh=Mock(return_value=True), observe=Mock(return_value=p)),
        "page": p,
        "decision": decision(),
        "goal": "Find a book",
        "history": [],
        "decisions": [],
        "status": "predicted",
        "started_at": time.perf_counter(),
        "record": False,
        "text_calls": [],
    }
    return a


def test_stale_decision_is_consumed_before_any_mutation(runner):
    runner.state["browser"].fresh.return_value = False
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_not_called()
    assert runner.state["decision"] is None


def test_generated_text_reused_only_for_identical_retry_context(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 1
    assert runner.state["browser"].act.call_count == 2  # The first call rejects before any browser input.
    assert runner.pending_text is None


def test_changed_field_context_does_not_reuse_generated_text(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["page"]["text"] = "Different page context"
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 2


def test_loading_waits_do_not_trigger_no_progress_stop(runner):
    for _ in range(5):
        runner.state["decision"] = decision("wait")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert len(runner.state["history"]) == 5 and runner.state["status"] == "ready"


def test_stale_observation_preserves_executed_action(runner):
    runner.state["decision"] = decision("e3")
    runner.state["browser"].observe.side_effect = StalePage("changed")
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"][-1]["action"] == "Go"
    runner.state["browser"].act.assert_called_once()


def test_observation_is_one_atomic_browser_read(monkeypatch):
    import jev_ultrafast.browser as browser

    p = page()
    cdp = Mock(return_value={"result": {"value": p}})
    monkeypatch.setattr(browser, "cdp", cdp)
    actual = browser_operation({"operation": "observe", "session": "test", "screenshot": False})
    assert actual["actions"] == p["actions"]
    assert cdp.call_count == 1
    assert cdp.call_args.args[0] == "Runtime.evaluate"


def test_executor_rejects_a_stale_page_before_browser_input(monkeypatch):
    import jev_ultrafast.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.fresh = Mock(return_value=False)
    operation = Mock()
    monkeypatch.setattr(browser, "browser_operation", operation)
    with pytest.raises(StalePage):
        b.act(page()["actions"][0], page(), "book")
    operation.assert_not_called()


@pytest.mark.parametrize("response", [{"exceptionDetails": {}}, {"result": {}}])
def test_interrupted_dropdown_mutation_cannot_be_retried_as_stale(monkeypatch, response):
    import jev_ultrafast.browser as browser

    # A navigation can destroy the evaluation result after the change event already fired.
    if "exceptionDetails" in response:
        response["exceptionDetails"] = {"text": "Execution context destroyed"}
    cdp = Mock(return_value=response)
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="Dropdown execution"):
        browser_operation({"operation": "act", "session": "test", "action": {
            "id": "e1", "kind": "select", "node": 1, "value": "Design",
        }})
    assert cdp.call_count == 1


def test_fingerprint_tracks_values_and_identity_not_screenshots():
    p = page()
    other = deepcopy(p)
    other["screenshot"] = "changed"
    assert fingerprint(p) == fingerprint(other)
    other["actions"][0]["node"] = 99
    assert fingerprint(p) != fingerprint(other)


@pytest.mark.parametrize("changed", ["Departure", "Where from?", "Where to?", "year"])
def test_flight_verification_rejects_wrong_trip(changed):
    from examples.flights import verify

    actual = {
        "url": "https://www.google.com/travel/flights/search?tfs=example",
        "text": "Track prices from Zürich to London departing 2026-09-20",
        "actions": [
            {"label": k, "value": v}
            for k, v in [
                ("Change ticket type. One way", "One way"),
                ("Where from?", "Zürich"),
                ("Where to?", "London"),
                ("Departure", "Sun, Sep 20"),
                ("Nonstop flight on Sunday, September 20. Select flight", ""),
            ]
        ],
    }
    assert verify(actual)["passed"]
    if changed == "year":
        actual["text"] = actual["text"].replace("2026", "2027")
    else:
        next(a for a in actual["actions"] if a["label"] == changed)["value"] = "wrong"
    assert not verify(actual)["passed"]


@pytest.mark.parametrize(
    "content", ["Thinking: Zurich", '{"text":null}', '{"text":"Zurich","extra":true}', '{"text":123}']
)
def test_text_helper_rejects_invalid_values(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ValueError, match="nothing typed"):
        model.field_text({"goal": "Find a flight"})


@pytest.mark.parametrize(
    ("content", "expected"),
    [('{"question":true,"answer":"It is 14 degrees and cloudy in Utrecht."}',
      "It is 14 degrees and cloudy in Utrecht."),
     ('{"question":false,"answer":null}', None),
     # An action request stays silent even when the helper summarises the page anyway.
     ('{"question":false,"answer":"The Eiffel Tower is 330 m tall."}', None)],
)
def test_answer_helper_returns_an_answer_or_none_for_an_action(monkeypatch, content, expected):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = Mock(return_value={"choices": [{"message": {"content": content}}]})
    monkeypatch.setattr(model, "post_json", post)
    context = model.answer_context("weather in Utrecht", page(), [])
    assert model.spoken_answer(context)[0] == expected
    body = post.call_args.args[2]
    assert body["messages"][0]["content"] == model.ANSWER
    assert json.loads(body["messages"][1]["content"])["request"] == "weather in Utrecht"


@pytest.mark.parametrize("content", [
    "It is 14 degrees", '{"answer":"14 degrees"}', '{"question":true,"answer":" "}', '{"question":true,"answer":1}',
    '{"question":"yes","answer":"14 degrees"}', '{"question":true,"answer":null}',
])
def test_answer_helper_rejects_invalid_answers(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ValueError, match="no valid answer"):
        model.spoken_answer({"request": "weather in Utrecht"})


def test_answers_use_their_own_model_and_fall_back_to_the_text_model(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setenv("TEXT_MODEL", "small")
    post = Mock(return_value={"choices": [{"message": {"content": '{"question":false,"answer":null}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    monkeypatch.delenv("ANSWER_MODEL", raising=False)
    model.spoken_answer({"request": "open it"})
    monkeypatch.setenv("ANSWER_MODEL", "reader")
    monkeypatch.setenv("ANSWER_MODEL_REASONING", "none")
    model.spoken_answer({"request": "open it"})
    bodies = [call.args[2] for call in post.call_args_list]
    assert [b["model"] for b in bodies] == ["small", "reader"]
    assert bodies[1]["reasoning"] == {"enabled": False}


def test_an_empty_helper_reply_is_asked_once_more(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    empty = {"choices": [{"message": {"content": None}}]}
    post = Mock(side_effect=[empty, {"choices": [{"message": {"content": '{"text":"Utrecht"}'}}]}])
    monkeypatch.setattr(model, "post_json", post)
    assert model.field_text({"goal": "train from Utrecht"})[0] == "Utrecht"
    post.side_effect = [empty, empty]
    with pytest.raises(ValueError, match="nothing typed"):
        model.field_text({"goal": "train from Utrecht"})


def done(runner):
    runner.state["browser"].document_text.return_value = "Utrecht weather: 14 °C, cloudy"
    runner.state.update(plan=["weather in Utrecht"], plan_index=0, decision={**decision("DONE"), "operation": "DONE"})
    return runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})


def test_done_reads_the_answer_from_the_finished_page(runner, monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    helper = Mock(return_value=("14 degrees and cloudy.", {"model": "test", "latency_ms": 5}))
    monkeypatch.setattr(loop, "spoken_answer", helper)
    state = done(runner)
    assert state["status"] == "done" and state["answer"] == "14 degrees and cloudy."
    context = helper.call_args.args[0]
    assert context["request"] == "weather in Utrecht"
    assert context["page"]["document_start"] == "Utrecht weather: 14 °C, cloudy"
    assert state["text_calls"][-1]["value"] == "14 degrees and cloudy."
    runner.state["browser"].act.assert_not_called()


def test_done_without_a_text_key_skips_the_answer(runner, monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    helper = Mock()
    monkeypatch.setattr(loop, "spoken_answer", helper)
    assert done(runner)["status"] == "done"
    helper.assert_not_called()


def test_a_failed_answer_keeps_the_task_done_and_reports_the_failure(runner, monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(loop, "spoken_answer", Mock(side_effect=RuntimeError("Model provider returned HTTP 402")))
    state = done(runner)
    assert state["status"] == "done" and not state.get("answer")
    assert "402" in state["answer_error"]


def test_a_follow_up_sees_the_earlier_answer(runner):
    runner.state.update(plan=["weather in Utrecht"], status="done", answer="14 degrees and cloudy.")
    runner.new_task("and tomorrow?")
    assert "weather in Utrecht (done; answered: 14 degrees and cloudy.)" in runner.state["goal"]
    assert runner.state["answer"] is None


def test_navigation_during_prediction_reobserves_without_action(runner):
    runner.state["browser"].fresh.side_effect = StalePage("Document navigating")
    runner.command("tick")
    assert runner.state["status"] == "ready"
    assert runner.state["decision"] is None
    runner.state["browser"].act.assert_not_called()


@pytest.mark.parametrize("page_changes, status", [(False, "blocked"), (True, "ready")])
def test_a_target_rejected_again_on_an_unchanged_page_stops_the_run(runner, monkeypatch, page_changes, status):
    monkeypatch.setattr(loop, "choose", Mock(return_value=decision("e3")))
    runner.state["browser"].act.side_effect = StalePage("Target changed or is covered. Observe again.")
    pages = iter(range(10))
    runner.state["browser"].observe.side_effect = lambda **_: {
        **page(),
        "marker": next(pages) if page_changes else "same",
    }
    runner.state.update(page=runner.observe(), status="ready")
    for _ in range(loop.STALE_REPEATS):
        runner.command("tick")
    assert runner.state["status"] == status
    assert runner.state["history"] == []


def test_follow_up_continues_on_the_open_page_with_earlier_requests_as_context(runner):
    runner.state.update(plan=["look up an image of a horse"], status="done", history=[{"action": "Images"}])
    runner.new_task("play a video of a horse")
    runner.state["browser"].navigate.assert_not_called()
    assert runner.state["status"] == "ready" and runner.state["history"] == []
    assert runner.state["plan"] == ["look up an image of a horse", "play a video of a horse"]
    assert runner.state["plan_index"] == 1
    goal = runner.state["goal"]
    assert "- look up an image of a horse" in goal and goal.endswith("play a video of a horse")


def test_follow_up_naming_a_site_opens_it_in_the_same_tab(runner):
    runner.state["plan"] = ["look up elon musk on x.com"]
    runner.new_task("open youtube.com", "https://youtube.com")
    runner.state["browser"].navigate.assert_called_once_with("https://youtube.com")


@pytest.mark.parametrize(("enabled", "url", "offered"), [
    (False, "https://example.test/", False),
    (True, "https://example.test/", True),
    (True, "https://www.google.com/?hl=en", False),
])
def test_web_search_is_offered_only_in_conversations_and_away_from_search(runner, enabled, url, offered):
    p = page()
    p["url"] = url
    runner.state["browser"].observe.return_value = p
    runner.state["web_search"] = enabled
    actions = runner.observe()["actions"]
    search = next((a for a in actions if a["id"] == "web_search"), None)
    assert (search is not None) is offered
    assert ("WEB_SEARCH" in model.action_space(actions)[2]) is offered
    if search:
        # Names the open site, so the model weighs "is this request about example.test?".
        assert "instead of example.test" in search["label"] and "{site}" not in search["label"]


def test_web_search_navigates_to_a_fixed_address(monkeypatch):
    import jev_ultrafast.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.fresh = Mock(return_value=True)
    b.navigate = Mock()
    operation = Mock()
    monkeypatch.setattr(browser, "browser_operation", operation)
    b.act(loop.WEB_SEARCH, page())
    b.navigate.assert_called_once_with(browser.SEARCH_URL)
    operation.assert_not_called()


def test_a_click_that_opens_a_new_tab_moves_the_run_there(monkeypatch):
    import jev_ultrafast.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.target = "jev"
    b.attach = Mock()
    b.wait_for_load = Mock()
    targets = [
        {"targetId": "jev", "type": "page"},
        {"targetId": "users-tab", "type": "page"},
        {"targetId": "wiki", "type": "page", "openerId": "jev"},
    ]
    cdp = Mock(return_value={"targetInfos": targets})
    monkeypatch.setattr(browser, "cdp", cdp)
    b.follow_new_tab()
    b.attach.assert_called_once_with("wiki")
    cdp.assert_any_call("Target.closeTarget", targetId="jev")
    assert all(c.kwargs.get("targetId") != "users-tab" for c in cdp.call_args_list)


def test_cycling_between_pages_stops_even_when_nodes_are_rebuilt(runner):
    def visit(url, label, node):
        p = page()
        p["url"] = url
        p["actions"][2].update(label=label, node=node)  # e3; a client-side app rebuilds it on every visit
        p["fingerprint"] = fingerprint(p)
        return p

    visits = [visit("https://example.test/a", "Home", 30 + i) if i % 2 == 0 else
              visit("https://example.test/", "Newest article", 30 + i) for i in range(6)]
    runner.state["page"] = visit("https://example.test/", "Newest article", 29)
    runner.state["browser"].observe.side_effect = visits
    for step in range(5):
        runner.state["decision"] = decision("e3")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
        assert runner.state["status"] == ("blocked" if step == 4 else "ready")


def test_a_client_side_route_change_counts_as_leaving_the_page():
    import jev_ultrafast.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.clicked_page = [1.0, "https://nos.nl/"]
    b.evaluate = Mock(return_value=[1.0, "https://nos.nl/artikel/1"])
    assert b.left_page()
    b.evaluate.return_value = [1.0, "https://nos.nl/"]
    assert not b.left_page()


def map_page():
    p = page()
    p["actions"].insert(0, {"id": "e0", "kind": "place", "label": "Map", "role": "map", "value": "", "node": 5})
    p["fingerprint"] = fingerprint(p)
    return p


def map_reply(content):
    return Mock(return_value={"choices": [{"message": {"content": content}}]})


def test_a_tile_map_is_one_element_with_its_own_operation():
    elements, targets, _ = model.action_space(map_page()["actions"])
    assert elements[0]["role"] == "map" and elements[0]["operations"] == ["PLACE_ON_MAP"]
    assert targets["PLACE_ON_MAP"]["1"]["id"] == "e0"


def test_map_helper_sees_the_screenshot_and_returns_a_place_not_a_pixel(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = map_reply('{"place":"Kerala","lat":10.85,"lng":76.27}')
    monkeypatch.setattr(model, "post_json", post)
    place, helper = model.map_place(model.map_context("Guess", page(), []), "SCREENSHOT")
    assert place == {"place": "Kerala", "lat": 10.85, "lng": 76.27}
    content = post.call_args.args[2]["messages"][1]["content"]
    assert content[1]["image_url"]["url"] == "data:image/jpeg;base64,SCREENSHOT"


@pytest.mark.parametrize("content", [
    '{"place":"X","lat":91,"lng":0}', '{"place":"X","lat":0,"lng":200}', '{"place":"X","lat":"10","lng":0}',
    '{"place":"","lat":0,"lng":0}', '{"place":"X","lat":0,"lng":0,"x":5}', '{"place":"X","lat":0}', "Kerala",
])
def test_map_helper_rejects_invalid_places(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", map_reply(content))
    with pytest.raises(ValueError, match="nothing clicked"):
        model.map_place({"goal": "Guess"}, "SCREENSHOT")


def test_placing_passes_coordinates_to_the_executor_and_logs_them(runner, monkeypatch):
    runner.state.update(page=map_page(), decision={**decision("e0"), "operation": "PLACE_ON_MAP"})
    runner.state["browser"].screenshot = Mock(return_value="SHOT")
    place = {"place": "Kerala", "lat": 10.85, "lng": 76.27}
    monkeypatch.setattr(loop, "map_place", Mock(return_value=(place, {"model": "test", "latency_ms": 5})))
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["browser"].act.call_args.kwargs["place"] == place
    assert runner.state["history"][-1]["text"] == "Kerala (10.85, 76.27)"


def test_a_placed_point_shows_as_the_map_value_until_another_action(runner, monkeypatch):
    choose = Mock(return_value=decision("e3"))
    monkeypatch.setattr(loop, "choose", choose)
    runner.state.update(page=map_page(), status="ready")
    runner.state["history"] = [{"kind": "place", "text": "Kerala (10.85, 76.27)", "page_changed": True}]
    runner.command("predict")
    assert choose.call_args.args[0]["actions"][0]["value"] == "point placed: Kerala (10.85, 76.27)"
    runner.state["history"].append({"kind": "click", "text": None, "page_changed": True})
    runner.state["status"] = "ready"
    runner.command("predict")
    assert choose.call_args.args[0]["actions"][0]["value"] == ""


def test_a_declined_placement_clicks_nothing_and_hides_the_map_on_that_page(runner, monkeypatch):
    runner.state.update(page=map_page(), decision={**decision("e0"), "operation": "PLACE_ON_MAP"})
    runner.state["browser"].screenshot = Mock(return_value="SHOT")
    monkeypatch.setattr(loop, "map_place", Mock(return_value=(None, {"model": "test", "latency_ms": 5})))
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_not_called()
    assert runner.state["history"][-1]["page_changed"] is False and runner.state["status"] == "ready"
    choose = Mock(return_value=decision("e3"))
    monkeypatch.setattr(loop, "choose", choose)
    runner.command("predict")
    assert all(a["kind"] != "place" for a in choose.call_args.args[0]["actions"])
