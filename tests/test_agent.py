"""Offline contracts for a dynamic operation/target policy. No paid APIs."""

import io
import json
import sys
import time
from copy import deepcopy
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import model
from jev_ultrafast.browser import StalePage, browser_operation, fingerprint
from jev_ultrafast.console import say


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


def test_each_helper_can_sit_on_its_own_provider(monkeypatch):
    """A free Mercury key for TYPE_TEXT must not drag the answer and map helpers onto that provider."""
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "shared")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://openrouter.ai/api/v1/")
    monkeypatch.delenv("ANSWER_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("ANSWER_MODEL_API_KEY", raising=False)
    assert model.helper_endpoint("ANSWER_MODEL") == ("https://openrouter.ai/api/v1", "shared")

    monkeypatch.setenv("TEXT_MODEL_BASE_URL_UNUSED", "ignored")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "shared")
    monkeypatch.setenv("MAP_MODEL_API_KEY", "own")
    monkeypatch.setenv("MAP_MODEL_BASE_URL", "https://api.inceptionlabs.ai/v1")
    assert model.helper_endpoint("MAP_MODEL") == ("https://api.inceptionlabs.ai/v1", "own")
    # The helper without its own pair keeps the shared one.
    assert model.helper_endpoint("ANSWER_MODEL") == ("https://openrouter.ai/api/v1", "shared")

    # A blank slot in .env counts as unset, so pasting nothing leaves the shared provider in charge.
    monkeypatch.setenv("HELPER_API_KEY", "shared")
    monkeypatch.setenv("HELPER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "")
    assert model.helper_endpoint("TEXT_MODEL") == ("https://openrouter.ai/api/v1", "shared")


def test_a_helpers_own_credential_is_required_by_name(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("MAP_MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="MAP_MODEL_API_KEY or HELPER_API_KEY or TEXT_MODEL_API_KEY"):
        model.helper_endpoint("MAP_MODEL")


@pytest.fixture
def runner():
    a = loop.Agent.__new__(loop.Agent)
    a.screenshots = False
    a.pending_text = None
    p = page()
    a.state = {
        "browser": Mock(
            fresh=Mock(return_value=True),
            observe=Mock(return_value=p),
            # Every stop reads the page out loud now, so the document is text, as the browser always returns.
            document_text=Mock(return_value=""),
        ),
        "page": p,
        "decision": decision(),
        "goal": "Find a book",
        "plan": ["Find a book"],
        "plan_index": 0,
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


@pytest.mark.parametrize(
    ("content", "expected"),
    # An action request stays silent only when it finished; a run that stopped says how far it got either way.
    [('{"question":false,"answer":"I finished all five rounds with 18,432 points."}',
      "I finished all five rounds with 18,432 points."),
     ('{"question":true,"answer":"I got as far as typing 5*5 into the search box."}',
      "I got as far as typing 5*5 into the search box.")],
)
def test_a_stopped_run_speaks_even_for_an_action_request(monkeypatch, content, expected):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = Mock(return_value={"choices": [{"message": {"content": content}}]})
    monkeypatch.setattr(model, "post_json", post)
    context = model.answer_context("play a round of the game", page(), [], outcome="stopped")
    assert model.spoken_answer(context)[0] == expected
    assert json.loads(post.call_args.args[2]["messages"][1]["content"])["outcome"] == "stopped"


def test_a_stopped_run_that_says_nothing_is_a_failed_answer(monkeypatch):
    """Silence is what this change exists to remove, so an empty reply is an error, not an action request."""
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(
        return_value={"choices": [{"message": {"content": '{"question":false,"answer":null}'}}]}))
    with pytest.raises(ValueError, match="no valid answer"):
        model.spoken_answer(model.answer_context("play a round", page(), [], outcome="stopped"))


def test_answers_use_their_own_model_and_fall_back_to_the_text_model(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://openrouter.ai/api/v1")
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
    # reasoning_effort, not OpenRouter's reasoning object: Inception ignores that one.
    assert [b["reasoning_effort"] for b in bodies] == ["low", "none"]


def test_deepseek_keeps_its_own_reasoning_switch(monkeypatch):
    """reasoning_effort is the shared spelling; DeepSeek is the one provider that needs its own."""
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("TEXT_MODEL", "deepseek-chat")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    model.field_text({"goal": 'Enter "Zurich"'})
    body = post.call_args.args[2]
    assert body["thinking"] == {"type": "disabled"} and "reasoning_effort" not in body


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


def stopped(runner, request, page_text):
    runner.state["browser"].document_text.return_value = page_text
    runner.state.update(plan=[request], plan_index=0, decision={**decision("BLOCKED"), "operation": "BLOCKED"})
    return runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})


def test_a_stopped_run_reads_what_it_reached_off_the_page(runner, monkeypatch):
    """A finished game stops for want of a next move. "I got stuck" hides the score the page is showing."""
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    helper = Mock(return_value=("I finished all five rounds with 18,432 points.", {"model": "t", "latency_ms": 5}))
    monkeypatch.setattr(loop, "spoken_answer", helper)
    state = stopped(runner, "play a round of the game", "Game over — 18,432 points")
    assert state["status"] == "blocked"
    assert state["answer"] == "I finished all five rounds with 18,432 points."
    context = helper.call_args.args[0]
    assert context["outcome"] == "stopped" and context["page"]["document_start"] == "Game over — 18,432 points"
    assert state["text_calls"][-1]["value"] == "I finished all five rounds with 18,432 points."


def test_a_stopped_run_without_a_text_key_stays_silent(runner, monkeypatch):
    for name in ("ANSWER_MODEL_API_KEY", "HELPER_API_KEY", "TEXT_MODEL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    helper = Mock()
    monkeypatch.setattr(loop, "spoken_answer", helper)
    assert stopped(runner, "play a round", "Game over")["status"] == "blocked"
    helper.assert_not_called()


@pytest.mark.parametrize("name", ["ANSWER_MODEL_API_KEY", "HELPER_API_KEY", "TEXT_MODEL_API_KEY"])
def test_any_key_the_answer_helper_would_use_lets_the_run_speak(runner, monkeypatch, name):
    """The gate has to ask the question the call asks. TEXT_MODEL_API_KEY alone used to decide it, so a
    configuration naming only HELPER_API_KEY -- which helper_endpoint documents as enough -- said nothing."""
    for other in ("ANSWER_MODEL_API_KEY", "HELPER_API_KEY", "TEXT_MODEL_API_KEY"):
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(name, "test")
    helper = Mock(return_value=("I got as far as the front page.", {"model": "t", "latency_ms": 5}))
    monkeypatch.setattr(loop, "spoken_answer", helper)
    assert stopped(runner, "play a round", "Game over")["answer"] == "I got as far as the front page."
    assert model.helper_key("ANSWER_MODEL") == "test"


def test_a_run_stopped_by_a_refused_target_speaks_too(runner, monkeypatch):
    """The loop's own guards stop a run as often as the model does; each one ends on a readable page."""
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    helper = Mock(return_value=("I typed 5*5 but could not submit it.", {"model": "t", "latency_ms": 5}))
    monkeypatch.setattr(loop, "spoken_answer", helper)
    monkeypatch.setattr(loop, "choose", Mock(return_value=decision("e3")))
    runner.state["browser"].act.side_effect = StalePage("Target changed or is covered. Observe again.")
    runner.state["browser"].observe.side_effect = lambda **_: {**page(), "marker": "same"}
    runner.state.update(page=runner.observe(), status="ready")
    for _ in range(loop.STALE_REPEATS):
        runner.command("tick")
    assert runner.state["status"] == "blocked"
    assert runner.state["answer"] == "I typed 5*5 but could not submit it."
    assert helper.call_args.args[0]["outcome"] == "stopped"


def test_a_refused_target_is_withheld_so_another_way_in_can_be_chosen(runner, monkeypatch):
    """A refusal executes nothing, so no history entry records it and an unchanged page returns the same
    choice forever. Withholding the target is the only way the model learns to press Enter instead."""
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    chooser = Mock(return_value=decision("e3"))
    monkeypatch.setattr(loop, "choose", chooser)
    runner.state["browser"].act.side_effect = StalePage("Target changed or is covered. Observe again.")
    runner.state["browser"].observe.side_effect = lambda **_: {**page(), "marker": "same"}
    runner.state.update(page=runner.observe(), status="ready")
    runner.command("tick")  # The first choice was made before the executor refused it.
    assert [a["id"] for a in chooser.call_args.args[0]["actions"]].count("e3") == 1
    assert runner.state["rejected"]["ids"] == ["e3"]
    runner.command("tick")
    offered = [a["id"] for a in chooser.call_args.args[0]["actions"]]
    assert "e3" not in offered and "key_enter" in offered and "e1" in offered


def test_a_refused_target_returns_once_the_page_accepts_an_action(runner, monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    chooser = Mock(return_value=decision("e3"))
    monkeypatch.setattr(loop, "choose", chooser)
    runner.state["browser"].act.side_effect = StalePage("Target changed or is covered. Observe again.")
    runner.state["browser"].observe.side_effect = lambda **_: {**page(), "marker": "same"}
    runner.state.update(page=runner.observe(), status="ready")
    runner.command("tick")
    assert runner.state["rejected"]["ids"] == ["e3"]
    runner.state["browser"].act.side_effect = None
    runner.command("tick")  # e3 is still withheld here; this tick is what clears it.
    assert runner.state["rejected"] is None
    runner.command("tick")
    offered = [a["id"] for a in chooser.call_args.args[0]["actions"]]
    assert "e3" in offered


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


@pytest.mark.parametrize("earlier_page", [True, False])
def test_back_is_offered_only_when_there_is_an_earlier_page(runner, earlier_page):
    runner.state["browser"].can_go_back.return_value = earlier_page
    runner.state["browser"].observe.return_value = page()
    ids = [a["id"] for a in runner.observe()["actions"]]
    assert ("go_back" in ids) == earlier_page
    assert "key_enter" in ids and "type_keys" in ids


def test_a_near_tie_from_rounded_probabilities_is_accepted():
    answer = {"choice": "down", "confidence": 0.23, "probabilities": {"left": 0.34, "down": 0.33, "up": 0.33}}
    assert model.validate_choice(answer, {"left", "down", "up"}) == answer


def test_a_key_that_changed_nothing_is_not_offered_again_on_that_page(runner, monkeypatch):
    up = next(a for a in loop.KEY_ACTIONS if a["key"] == "ArrowUp")
    runner.state["page"]["actions"] += loop.KEY_ACTIONS
    runner.state["page"]["fingerprint"] = fingerprint(runner.state["page"])
    runner.state["browser"].observe.return_value = runner.state["page"]  # The board did not move.
    runner.state["decision"] = {**decision(up["id"]), "operation": "PRESS_KEY", "target": "ArrowUp"}
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"][-1]["page_changed"] is False
    choose = Mock(return_value=decision("e3"))
    monkeypatch.setattr(loop, "choose", choose)
    runner.command("predict")
    offered = {a.get("key") for a in choose.call_args.args[0]["actions"]}
    assert "ArrowUp" not in offered and "ArrowDown" in offered


def test_keys_are_targets_of_one_operation_not_page_elements():
    elements, targets, controls = model.action_space([*page()["actions"], *loop.KEY_ACTIONS, loop.TYPE_KEYS])
    assert len(elements) == 2
    assert set(targets["PRESS_KEY"]) == {"Enter", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
                                         "Backspace", "Tab"}
    assert "TYPE_KEYS" in controls


def key_events(monkeypatch, action, text=None):
    import jev_ultrafast.browser as browser

    sent = []
    monkeypatch.setattr(browser, "session_cdp", lambda method, _session, **params: sent.append((method, params)))
    browser.browser_operation({"operation": "act", "session": "s", "action": action, "text": text, "place": None})
    return [(p["type"], p["key"], p.get("text")) for m, p in sent if m == "Input.dispatchKeyEvent"]


def test_press_key_sends_a_real_key_press(monkeypatch):
    arrow = next(a for a in loop.KEY_ACTIONS if a["key"] == "ArrowUp")
    assert key_events(monkeypatch, arrow) == [("rawKeyDown", "ArrowUp", None), ("keyUp", "ArrowUp", None)]
    enter = next(a for a in loop.KEY_ACTIONS if a["key"] == "Enter")
    assert key_events(monkeypatch, enter)[0] == ("keyDown", "Enter", "\r")


@pytest.mark.parametrize(("action", "text"), [
    ({**loop.KEY_ACTIONS[0], "key": "F5"}, None),
    (loop.TYPE_KEYS, "rm -rf"),
    (loop.TYPE_KEYS, ""),
    (loop.TYPE_KEYS, "x" * 101),
])
def test_only_fixed_keys_and_plain_letters_are_sent(monkeypatch, action, text):
    with pytest.raises(ValueError):
        key_events(monkeypatch, action, text)


def test_typed_keys_are_one_press_per_letter(monkeypatch):
    events = key_events(monkeypatch, loop.TYPE_KEYS, "Crane")
    assert [e for e in events if e[0] == "keyDown"] == [("keyDown", c, c) for c in "Crane"]


def test_type_keys_gets_its_letters_from_the_text_helper(runner, monkeypatch):
    helper = Mock(return_value=("crane", {"model": "test", "latency_ms": 5}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["page"]["actions"].append(loop.TYPE_KEYS)
    runner.state["decision"] = {**decision("type_keys"), "operation": "TYPE_KEYS", "target": None}
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_called_once()
    assert runner.state["browser"].act.call_args.kwargs["text"] == "crane"
    assert runner.state["history"][-1]["text"] == "crane"


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


def rerendered(i, keys=False):
    """The same controls, on a page whose content is new every time: what a filter that re-renders a list does."""
    p = page()
    p["text"] = f"Search results {i}"
    if keys:
        p["actions"] = [*p["actions"],
                        {"id": "key_arrowdown", "kind": "key", "key": "ArrowDown", "label": "Arrow down"}]
    p["fingerprint"] = fingerprint(p)
    return p


def clicking(runner, monkeypatch, choices, keys=False):
    for name in ("ANSWER_MODEL_API_KEY", "HELPER_API_KEY", "TEXT_MODEL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    runner.state["page"] = rerendered(0, keys)
    runner.state["browser"].observe.side_effect = [rerendered(i, keys) for i in range(1, len(choices) + 1)]
    for selected in choices:
        runner.state["decision"] = decision(selected)
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
        yield runner.state["status"]


def test_clicking_one_control_over_and_over_stops_even_when_the_page_changes(runner, monkeypatch):
    """from_view holds the page text, so a control that re-renders the page looks like a new situation at every
    click and CYCLE_REPEATS never fires. A recorded run clicked one such filter eight times."""
    statuses = list(clicking(runner, monkeypatch, ["e3"] * loop.CLICK_REPEATS))
    assert statuses == ["ready"] * (loop.CLICK_REPEATS - 1) + ["blocked"]


def test_one_click_short_of_the_limit_keeps_going(runner, monkeypatch):
    assert list(clicking(runner, monkeypatch, ["e3"] * (loop.CLICK_REPEATS - 1))) == \
        ["ready"] * (loop.CLICK_REPEATS - 1)


def test_another_click_in_between_resets_the_count(runner, monkeypatch):
    """Only an unbroken run counts: alternating between two controls is the cycle guard's business, not this."""
    choices = ["e3"] * (loop.CLICK_REPEATS - 1) + ["e2"] + ["e3"] * (loop.CLICK_REPEATS - 1)
    assert set(clicking(runner, monkeypatch, choices)) == {"ready"}


def test_repeating_one_key_is_not_a_repeated_click(runner, monkeypatch):
    """A game presses one arrow all game and a puzzle types letter after letter; only clicks are counted."""
    presses = ["key_arrowdown"] * (loop.CLICK_REPEATS + 2)
    assert set(clicking(runner, monkeypatch, presses, keys=True)) == {"ready"}



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


def cp1252_console(monkeypatch):
    """A Windows console in the default code page: what every measured suite run printed to."""
    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", console)
    return console


def test_a_label_the_console_cannot_show_does_not_end_the_request(runner, monkeypatch):
    """One request per measured suite run died here: a YouTube title holding an emoji reached a print, which
    raised UnicodeEncodeError out of `tick` and was recorded as that request's error. What a console can
    render decides what is shown, never whether the run goes on."""
    console = cp1252_console(monkeypatch)
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    monkeypatch.setattr(loop, "choose", Mock(return_value=decision("e3")))
    titled = page()
    titled["actions"][2]["label"] = "We tried it 🤔"
    titled["fingerprint"] = fingerprint(titled)
    runner.state["browser"].act.side_effect = StalePage("Target changed or is covered. Observe again.")
    runner.state["browser"].observe.side_effect = lambda **_: {**titled, "marker": "same"}
    runner.state.update(page=runner.observe(), status="ready")
    runner.command("tick")
    assert runner.state["status"] == "ready"
    console.flush()
    assert b"target=We tried it ?" in console.buffer.getvalue()


def test_a_console_that_can_show_the_character_still_gets_it(monkeypatch):
    """The replacement is the console's own limit, not a strip to ASCII: nothing is lost where it fits."""
    console = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", console)
    say("We tried it 🤔")
    console.flush()
    assert console.buffer.getvalue().decode("utf-8").strip() == "We tried it 🤔"
