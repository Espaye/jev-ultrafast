"""Verify a pasted Inception key end to end, then wire TYPE_TEXT to it.

Reads INCEPTION_API_KEY from .env, finds the base URL and the native model id by asking the provider
rather than assuming them, and runs a real TYPE_TEXT-shaped call. Reports only; --apply writes
TEXT_MODEL_API_KEY / TEXT_MODEL_BASE_URL / TEXT_MODEL into .env once the call has actually worked.
The answer and map helpers stay on HELPER_* and are never touched.
"""

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
CANDIDATES = ("https://api.inceptionlabs.ai/v1", "https://api.inception.ai/v1")


def read_env():
    values = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env(updates):
    lines = ENV.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        key = line.partition("=")[0].strip()
        if not line.strip().startswith("#") and "=" in line and key in updates:
            lines[index] = f"{key}={updates.pop(key)}"
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    key = read_env().get("INCEPTION_API_KEY", "")
    if not key:
        print("INCEPTION_API_KEY is empty in .env — paste the key on that line and run this again.")
        return 1
    client = httpx.Client(http2=True, timeout=30)
    headers = {"Authorization": f"Bearer {key}"}

    base, models = None, []
    for candidate in CANDIDATES:
        try:
            response = client.get(candidate + "/models", headers=headers)
        except httpx.HTTPError as error:
            print(f"  {candidate}/models — unreachable ({type(error).__name__})")
            continue
        print(f"  {candidate}/models — HTTP {response.status_code}")
        if response.is_success:
            base = candidate
            models = [m.get("id") for m in response.json().get("data", []) if m.get("id")]
            break
    if not base:
        print("No Inception base URL answered. Check the key, or the URL in your platform console.")
        return 1
    print(f"\nBase URL: {base}\nModels offered: {', '.join(models) or '(none listed)'}")

    # Keep the model already in use; its native id is the OpenRouter one without the provider prefix.
    # Picking whatever happens to be listed first would quietly downgrade the agent.
    current = read_env().get("TEXT_MODEL", "").rpartition("/")[2]
    preferred = [m for m in models if "mercury" in m.lower()]
    preferred.sort(key=lambda m: (m != current, m))
    if not preferred:
        print("No mercury model in the listing; nothing to switch TYPE_TEXT to.")
        return 1

    # The field helper's real shape: JSON object out, reasoning off, the window the agent uses.
    from jev_ultrafast.model import field_context
    from jev_ultrafast.questions import TEXT_VALUE

    context = field_context("Search for a wireless keyboard and open the cheapest one",
                            {"label": "Search products", "role": "searchbox", "value": ""},
                            {"title": "Coolblue", "text": "Coolblue - Search products. Keyboards, mice."}, [])
    working = []
    for model_id in preferred:
        started = time.perf_counter()
        try:
            response = client.post(base + "/chat/completions", headers=headers, json={
                "model": model_id, "max_tokens": 1024, "response_format": {"type": "json_object"},
                "reasoning_effort": "none",
                "messages": [{"role": "system", "content": TEXT_VALUE},
                             {"role": "user", "content": json.dumps(context)}]})
        except httpx.HTTPError as error:
            print(f"  {model_id}: unreachable ({type(error).__name__})")
            continue
        elapsed = time.perf_counter() - started
        if not response.is_success:
            print(f"  {model_id}: HTTP {response.status_code} {response.text[:160]}")
            continue
        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
            value = json.loads(content)["text"]
        except (KeyError, IndexError, TypeError, ValueError):
            print(f"  {model_id}: unusable reply {str(body.get('choices'))[:160]}")
            continue
        tokens = body.get("usage", {}).get("completion_tokens")
        print(f"  {model_id}: {value!r} — {elapsed:.2f}s — {tokens} completion tokens")
        working.append(model_id)

    if not working:
        print("\nNo mercury model returned a usable field value. TYPE_TEXT stays on OpenRouter.")
        return 1
    chosen = working[0]
    if current and current not in working:
        print(f"Note: {current} is in use today but did not work here; falling back to {chosen}.")
    print(f"\nWorks: {chosen} on {base}")
    if "--apply" not in sys.argv:
        print("Report only. Re-run with --apply to point TYPE_TEXT at it.")
        return 0
    write_env({"TEXT_MODEL_API_KEY": key, "TEXT_MODEL_BASE_URL": base, "TEXT_MODEL": chosen})
    print("Applied. TYPE_TEXT now uses Inception directly; answer and map helpers still use HELPER_*.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
