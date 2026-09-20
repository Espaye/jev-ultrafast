# Jev Ultrafast

Read README.md before editing. Keep the loop small: page -> indexed elements -> operation + target -> execution.

- The input is one natural-language goal. Do not add site-specific plans or hardcoded field values.
- TypeSafe chooses an operation and operation-specific target heads in one request. Consume only the selected operation's target.
- Targets must map to observed elements and supported operations. Never let the model emit selectors or executable code.
- PLACE_ON_MAP invokes the vision helper for a latitude/longitude only; code owns the projection, panning and hit test.
- PRESS_KEY chooses from the fixed KEYS list; TYPE_KEYS letters come from the text LLM and only letters, digits and spaces are sent. GO_BACK and WEB_SEARCH are code-owned navigation.
- TYPE_TEXT invokes the text LLM. Cache a stale retry's value only while its entire helper input is identical.
- Never retry a browser mutation. Log execution before observing its result.
- Screenshots are optional; the model does not consume them. Keep demonstration footage at its original speed.
- Keep credentials server-side and .env ignored. Tests must not call paid APIs.
- Verify actual final outcomes independently. A DONE choice is not proof of success.
- Keep examples, README claims, raw evidence, and model-call counts consistent.
- Commit and push a finished round yourself: checks green, evaluation measured and written up. Leave
  unfinished or unmeasured work in the tree and say so.
- Each helper resolves its own endpoint (<SETTING>_API_KEY/_BASE_URL, then the shared HELPER_* pair). Send
  reasoning_effort, not a provider-specific reasoning object: Inception ignores OpenRouter's and fills the
  token window until the reply comes back empty.

Checks: uv run ruff check ., uv run pytest, node --check jev_ultrafast/static/app.js,
node --check jev_ultrafast/snapshot.js, uv build, uv run python scripts/check_guards.py.
