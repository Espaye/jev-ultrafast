"""TypeSafe makes choices; an optional small OpenAI-compatible model writes field values."""

import datetime
import json
import math
import os
import time

import httpx

from .console import say
from .questions import ANSWER, MAP_PLACE, NEXT_ACTION, TARGET, TEXT_VALUE

CLIENT = httpx.Client(http2=True, timeout=25)


def post_json(url, key, body):
    for attempt in range(3):
        try:
            response = CLIENT.post(
                url, json=body, headers={"Authorization": f"Bearer {key}"}
            )
        except httpx.HTTPError:
            raise RuntimeError("Model connection failed; no action executed.") from None
        if response.status_code in {429, 529, 503} and attempt < 2:
            time.sleep(0.5 * 2**attempt)
            continue
        if response.is_error:
            raise RuntimeError(
                f"Model provider returned HTTP {response.status_code}; no action executed."
            )
        return response.json()
    raise RuntimeError("Model unavailable")


def validate_choice(answer, ids):
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(
                type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1
                for n in numbers
            )
            and abs(sum(probabilities.values()) - 1) < 0.02
            # Probabilities arrive rounded to two decimals, so a near-tie (0.33 chosen beside 0.34) is still the top.
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 0.011
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT", "place": "PLACE_ON_MAP"}
    for action in actions:
        kind = action["kind"]
        if kind == "key":
            # Keys are targets of their own operation, not page elements.
            targets.setdefault("PRESS_KEY", {})[action["key"]] = action
            continue
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {
                k: action[k]
                for k in ("role", "value", "checked", "selected", "expanded")
                if k in action
            }
            element.update(
                index=index, label=action["label"].split(" → ")[0], operations=[]
            )
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append(
                {"index": target, "label": action["label"], "value": action["value"]}
            )
        group[target] = action
    return elements, targets, controls


def choose(state, goal, history):
    elements, targets, controls = action_space(state["actions"])
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
        "PLACE_ON_MAP": "Click a location on an observed map: a requested place, or a guess the page asks for. "
        "A helper that sees the page picks the location from the goal.",
        "PRESS_KEY": "Press one keyboard key on the page: Enter to submit, Escape to close a dialog, an arrow to "
        "move in a game or list, Backspace to delete the last typed letter.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(
        DONE="Every requirement is visibly satisfied; for a question, the page shows its answer.",
        BLOCKED="No supported operation can progress.",
    )
    questions = {
        "operation": {
            "type": "choice",
            "criteria": operations,
            "instructions": {"goal": goal, "rules": NEXT_ACTION},
        }
    }
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{
                        k: a[k]
                        for k in ("role", "checked", "selected", "expanded")
                        if k in a
                    },
                }
                for index, a in candidates.items()
            },
            "instructions": {
                "goal": goal,
                "operation": operation,
                "rules": [NEXT_ACTION, TARGET],
            },
        }
    body = {
        "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        "state": {
            "page": {k: state[k] for k in ("url", "title", "text")},
            "elements": elements,
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")}
                for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    started = time.perf_counter()
    result = post_json(
        "https://api.typesafe.ai/v1/systemone", os.environ["TYPESAFE_API_KEY"], body
    )
    try:
        operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
        if operation_answer["choice"] in targets:
            validate_choice(
                result["answers"].get(operation_answer["choice"].lower() + "_target", {}),
                targets[operation_answer["choice"]],
            )
    except ValueError:
        say(f"JEV: invalid reply {json.dumps(result.get('answers'))[:600]}")
        raise
    operation = operation_answer["choice"]
    target = None
    target_answer = None
    probabilities = {}
    if operation in targets:
        # Unused target heads cannot cause an action. Validate the head selected by the operation.
        target_answer = validate_choice(
            result["answers"].get(operation.lower() + "_target", {}), targets[operation]
        )
        target = target_answer["choice"]
        choice = targets[operation][target]["id"]
        probabilities = {
            a["id"]: target_answer["probabilities"][index]
            for index, a in targets[operation].items()
        }
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = operation_answer["probabilities"][operation]
    latency_ms = round((time.perf_counter() - started) * 1000)
    say(f"JEV: {operation} {choice!r} — {latency_ms} ms — {result['model']}")
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "raw_answers": result["answers"],
        "model": result["model"],
        "usage": result.get("usage", {}),
        "latency_ms": latency_ms,
        "request": body,
    }


def reasoning_param(base, setting, default="low"):
    """reasoning_effort is the OpenAI-standard spelling and is honoured by OpenRouter and by Inception's own
    API. OpenRouter's {"reasoning": {...}} object is NOT: Inception ignores it silently, leaving reasoning on
    until the 1024-token window fills with it and the reply comes back empty. DeepSeek has its own switch."""
    if "api.deepseek.com/" in base:
        return {"thinking": {"type": "disabled"}}
    return {"reasoning_effort": os.environ.get(setting + "_REASONING") or default}


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [
            {k: h.get(k) for k in ("action", "text")} for h in history[-6:]
        ],
    }


def helper_key_names(setting):
    """The key variables this helper reads, in the order it reads them. An empty value counts as unset."""
    return tuple(dict.fromkeys([setting + "_API_KEY", "HELPER_API_KEY", "TEXT_MODEL_API_KEY"]))


def helper_key(setting):
    """The key this helper would actually send, or None when it has none. Whoever decides whether a helper can
    run must ask the same question the call itself asks: gating on one spelling of it (TEXT_MODEL_API_KEY)
    silently muted a configuration that names only HELPER_API_KEY, which helper_endpoint accepts."""
    return next((os.environ[n] for n in helper_key_names(setting) if os.environ.get(n)), None)


def helper_endpoint(setting):
    """Each helper may sit on its own provider. <SETTING>_API_KEY and <SETTING>_BASE_URL win where they are
    set; HELPER_API_KEY and HELPER_BASE_URL are the shared fallback (TEXT_MODEL_* is the older name for it,
    still honoured), so a one-provider setup needs no extra variables. The shared pair has a name of its own
    because TEXT_MODEL_* belongs to TYPE_TEXT: a free Mercury key there must not drag the gemini answer and
    map helpers onto Inception with it. An empty value counts as unset, so a blank slot falls back."""
    key = helper_key(setting)
    if not key:
        raise ValueError(
            f"{setting} needs {' or '.join(helper_key_names(setting))}; "
            "no value is hardcoded or guessed by the executor."
        )
    base = next(
        (
            os.environ[n]
            for n in (setting + "_BASE_URL", "HELPER_BASE_URL", "TEXT_MODEL_BASE_URL")
            if os.environ.get(n)
        ),
        "https://api.deepseek.com/v1",
    )
    return base.rstrip("/"), key


def map_context(goal, page, history):
    return {
        "goal": goal,
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [
            {k: h.get(k) for k in ("action", "text")} for h in history[-6:]
        ],
    }


def map_place(context, screenshot):
    """A vision model reads the page (a photo, a question) and names a place; code owns the pixel."""
    base, key = helper_endpoint("MAP_MODEL")
    model = os.environ.get("MAP_MODEL", "google/gemini-3.8-flash")
    started = time.perf_counter()
    result = post_json(
        base + "/chat/completions",
        key,
        {
            "model": model,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
            **reasoning_param(base, "MAP_MODEL"),
            "messages": [
                {"role": "system", "content": MAP_PLACE},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": json.dumps(context)},
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + screenshot}},
                    ],
                },
            ],
        },
    )
    invalid = ValueError("Map helper returned no valid place; nothing clicked.")
    try:
        output = json.loads(result["choices"][0]["message"]["content"])
        place, lat, lng = output["place"], output["lat"], output["lng"]
    except (ValueError, KeyError, TypeError):
        raise invalid from None
    if set(output) != {"place", "lat", "lng"}:
        raise invalid
    latency_ms = round((time.perf_counter() - started) * 1000)
    helper = {"model": model, "latency_ms": latency_ms, "usage": result.get("usage", {})}
    if place is None:
        say(f"MAP helper: nothing to place — {latency_ms} ms — {model}")
        return None, helper
    if (
        not isinstance(place, str)
        or not place.strip()
        or len(place) > 200
        or not all(type(n) in (int, float) and math.isfinite(n) for n in (lat, lng))
        or not (-85 <= lat <= 85 and -180 <= lng <= 180)
    ):
        raise invalid
    say(f"MAP helper: {place!r} ({lat}, {lng}) — {latency_ms} ms — {model}")
    return {"place": place.strip(), "lat": lat, "lng": lng}, helper


def text_json(operation, system, context, setting="TEXT_MODEL"):
    """One JSON reply from the OpenAI-compatible helper. setting names the model's variable (TEXT_MODEL, or
    ANSWER_MODEL for spoken answers, which falls back to the text model when unset)."""
    if not os.environ.get(setting):
        setting = "TEXT_MODEL"
    base, key = helper_endpoint(setting)
    model = os.environ.get(setting, "deepseek-chat")
    reasoning = reasoning_param(base, setting)
    started = time.perf_counter()
    # A reply without content changes nothing in the browser, so asking once more is safe.
    for _attempt in range(2):
        result = post_json(
            base + "/chat/completions",
            key,
            {
                "model": model,
                "max_tokens": 1024,
                "response_format": {"type": "json_object"},
                **reasoning,
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": json.dumps(context),
                    },
                ],
            },
        )
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, TypeError, IndexError):
            content = None
        if content:
            break
    latency_ms = round((time.perf_counter() - started) * 1000)
    helper = {"model": model, "latency_ms": latency_ms, "usage": result.get("usage", {})}
    try:
        output = json.loads(content)
    except (ValueError, TypeError):
        output = None
    if not isinstance(output, dict):
        say(f"{operation} helper: unusable reply {str(result.get('choices'))[:300]!r}")
    return output, helper


def answer_context(goal, page, history, document="", outcome="finished"):
    return {
        "request": goal,
        # "finished" or "stopped". A run that ran out of moves still ends on the page holding its result.
        "outcome": outcome,
        # "The next train" or "open now" depends on the time; timetables also list trips that already left.
        "now": datetime.datetime.now().astimezone().strftime("%A %Y-%m-%d %H:%M %Z"),
        "page": {"url": page["url"], "title": page["title"], "visible_text": page["text"][:6000],
                 "document_start": document[:8000]},
        "recent_actions": [
            {k: h.get(k) for k in ("action", "text")} for h in history[-6:]
        ],
    }


def spoken_answer(context):
    """What the run says out loud from the page it ended on. A finished action request stays silent; a run that
    stopped early always speaks, because "I got stuck" alone hides a played-out game and its score."""
    stopped = context.get("outcome") == "stopped"
    output, helper = text_json("A spoken answer", ANSWER, context, "ANSWER_MODEL")
    value = output.get("answer") if isinstance(output, dict) else ""
    question = output.get("question") if isinstance(output, dict) else None
    spoken = isinstance(value, str) and value.strip() and len(value) <= 600
    if (
        set(output or {}) != {"question", "answer"}
        or not isinstance(question, bool)
        or (question or stopped) and not spoken
    ):
        raise ValueError("Text helper returned no valid answer; the run ended but nothing was said.")
    if not question and not stopped:
        value = None  # A finished action request gets no answer, even if the helper wrote one anyway.
    value = value.strip() if value else None
    say(f"ANSWER helper: {value!r} — {helper['latency_ms']} ms — {helper['model']}")
    return value, helper


def field_text(context):
    output, helper = text_json("TYPE_TEXT", TEXT_VALUE, context)
    try:
        value = output["text"]
        if (
            set(output) != {"text"}
            or not isinstance(value, str)
            or not value.strip()
            or len(value) > 2000
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        say(f"TYPE_TEXT helper: invalid value {json.dumps(output)[:300]}")
        raise ValueError(
            "Text helper returned no valid field value; nothing typed."
        ) from None
    say(f"TEXT helper: {value!r} — {helper['latency_ms']} ms — {helper['model']}")
    return value, helper
