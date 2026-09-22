# Evaluation: spoken-style conversations on the real web

**28/30 requests passed** (93%) across 3 runs of 5 conversations; **13/15 conversations** passed every request. Median time per request **4.0 s**, median **3** Jev decisions per request.

Each conversation starts in a fresh tab of the same Chrome profile, on the site a request names or on a Google search, exactly as the inspector does. Follow-ups continue in that tab. A request passes only when its check holds on the final page; Jev's own `DONE` is never counted. Requests are fed as the text Chrome's speech recognition would produce, so this measures browsing, not hearing. Times include model calls, text generation, page loads and waits. Each request may use at most 40 decisions.

Text helper: `deepseek/deepseek-v4-flash-0731:free`. Operation and element: TypeSafe `jev-latest`. Source: identical in every run (SHA-256 per file in each `report.json`).

| Conversation | Request | Passed | Median time | Median decisions | What the check requires |
| --- | --- | --- | --- | --- | --- |
| news | “look up the latest news about the war in Yemen” | 3/3 | 4.5 s | 3 | Yemen news: search results or an article about it |
|  | “play the video” | 2/3 | 1.9 s | 3 | a video playing on the page, or open in Google's video player |
| hackernews | “go to news.ycombinator.com and open the comments of the top story” | 3/3 | 2.0 s | 2 | the comment page of the story that was first on the front page |
| youtube | “go to youtube.com and search for the moon landing” | 3/3 | 4.5 s | 5 | YouTube results for a moon landing query |
|  | “play the first video” | 3/3 | 2.1 s | 2 | a YouTube video playing |
|  | “open the channel of this video” | 2/3 | 3.0 s | 5 | a YouTube channel page |
| wikipedia | “find the Wikipedia article about the Eiffel Tower” | 3/3 | 6.5 s | 5 | the Eiffel Tower article |
|  | “now open the article about the man who designed it” | 3/3 | 1.6 s | 2 | the article about Eiffel, Koechlin or Nouguier |
| images | “look up a picture of a cow” | 3/3 | 5.4 s | 4 | Google Images results for cow |
|  | “show me sheep instead” | 3/3 | 4.0 s | 3 | Google Images results for sheep |

## Every failure

- Run 1, news, “play the video”: ended `blocked` at `https://www.aljazeera.com/video/live`. Actions: link to live stream video player → Wait for the page to update → link to live stream video player → link to live stream video player → link to live stream video player.
- Run 3, youtube, “open the channel of this video”: ended `blocked` at `https://www.youtube.com/watch?v=7WAWY-DktT0`. Actions: From Dutchsteammachine → From Dutchsteammachine → From Dutchsteammachine → From Dutchsteammachine → From Dutchsteammachine → From Dutchsteammachine → From Dutchsteammachine → From Dutchsteammachine.

Reproduce with `uv run --env-file .env python scripts/conversations.py <new-folder>` (paid model calls). Live sites change, so results vary from day to day.

## What the failures mean

- **Al Jazeera's live page never rendered a video** in Jev's tab: the player is a frame that stayed empty. Jev kept clicking “link to live stream video player”; the loop guard (same action, same-looking page, third time) stopped it as blocked instead of letting it run on.
- **“From Dutchsteammachine” is a recommendation filter, not the channel link.** Each click re-filtered the list, so the page changed every time and the loop guard did not fire; Jev stopped itself after eight clicks. A toggle like this is a known gap in the guard.

## How the checks were settled

Five development runs (not counted above) came first. They led to three changes before these final runs:

- nos.nl was replaced by Hacker News: a site blocker in the test Chrome profile started blocking nos.nl mid-session, and Jev's tab shares that profile.
- The Google Images check accepted only `udm=2`; Google now also uses `udm=imgs`.
- The Yemen news check required a Google results page. Jev sometimes opened a news article instead, which answers the request, so the check now accepts any page about Yemen news. “Play the video” now requires a playing video on whatever page Jev is on.

In the development runs the same code also produced one real failure that did not recur in the final runs: twice, Jev typed “cow” on Google, clicked the Images link instead of searching, and reported done on an empty Google Images page.

# Evaluation: spoken answers to questions

**18/18 requests passed** across 3 runs of 4 conversations (2026-09-19, 17:04–17:07). Median time per request **5.9 s**, median **3** Jev decisions per request.

Before this round, Jev answered every question with "Done". Now, when Jev chooses `DONE`, the answer model decides whether the request asked something and, if so, answers from the finished page: the text on screen, the top of the whole page, and the current local time. [`scripts/answers.py`](../scripts/answers.py) checks **what Jev says**, not only where it ends up. A number in the answer must appear on the final page, and it must also agree with a reference Jev never sees where one exists (Open-Meteo for the weather, fixed facts for the Eiffel Tower). A request that only asks for an action must get no answer.

Operation and element: TypeSafe `jev-latest`. Field text: `inception/mercury-2.5`. Spoken answers: `google/gemini-3.8-flash`, low reasoning. Source identical in every run. OpenRouter cost of the whole round, development included: $0.16.

| Conversation | Request | Passed | Median time | Median decisions | What the check requires |
| --- | --- | --- | --- | --- | --- |
| weather | “what's the weather in Utrecht right now” | 3/3 | 5.9 s | 3 | a current temperature within 3 °C of Open-Meteo, shown on the page |
|  | “and tomorrow?” | 3/3 | 2.0 s | 1 | a temperature within tomorrow's Open-Meteo range ± 3 °C |
| ns | “go to ns.nl and tell me when the next train from Utrecht Centraal to Amsterdam Centraal leaves” | 3/3 | 5.8 s | 4 | Utrecht → Amsterdam planned on ns.nl; the train that really leaves next, delays included |
| coolblue | “go to coolblue.nl and search for the Nintendo Switch 2, how much does it cost?” | 3/3 | 6.7 s | 4 | a euro price shown on coolblue.nl |
| eiffel | “find the Wikipedia article about the Eiffel Tower” | 3/3 | 7.7 s | 4 | no spoken answer: the request is an action |
|  | “how tall is it?” | 3/3 | 3.0 s | 2 | its height: 330 m (or 300/312/324 m, 1,083 ft) |

Typical answers: *"It is currently 21°C and cloudy in Utrecht, with a wind speed of 26 km/h."* · *"The next train to Amsterdam Centraal leaves at 17:09 from platform 5."* · *"The standalone Nintendo Switch 2 costs 499 euros on Coolblue, while bundles start at 524 euros."*

One flaw the checks let through: in run 3 the NS answer named the right train (17:09) but added that the delayed 16:54 train "is also leaving at 17:01". At 17:06 that train had already left.

Reproduce with `uv run --env-file .env python scripts/answers.py <new-folder>` (paid model calls).

## What development turned up

Nine development runs (not counted above) found these problems, each fixed before the final runs:

- **bol.com blocks this IP address** as suspected automated traffic. Jev correctly reported `blocked`; the conversation moved to coolblue.nl.
- **ns.nl's "Plannen" looked like any other button.** When the planner already held the stations (ns.nl remembers the last trip searched in the browser profile), Jev chose "Toon Reisopties" (a toggle) 93% of the time, then wandered into the site search. The page snapshot now names a form's submit button `submit button`, and Jev's rules say to read controls by meaning in the site's language. Jev then pressed Plannen first in every run.
- **The answer model did not know the time.** NS lists trips from just before the requested time, so "the next train" came back as one that had already left. Answers now get the local time, and the rules explain that a delayed train leaves at its planned time plus the delay.
- **Mercury was not reliable enough for answers.** Replaying the same saved NS page 5 times: Mercury named the right train 2–3 times; with a train running 7 minutes late, no model with reasoning off got it right. `gemini-3.8-flash` with low reasoning got 15/15 on the replays (≈1.5 s, ≈$0.0014 per answer). Field text stays on Mercury.
- **"Find the Wikipedia article" was answered with a summary.** The answer model now returns an explicit `question: true/false` before any answer, and code drops the answer for `false`.
- **"How tall is it?" said 320.75 m** from a table of historical heights in the section Jev had scrolled to. The answer model now also gets the top of the whole page, and the rules prefer the headline figure: 330 m in every final run.
- **An English question about a Dutch site was answered in Dutch**, which the English voice would mispronounce. The rules now name the request's language, not the page's.
- **An empty reply from the text model** (no content) once failed a field. Since nothing has touched the browser at that point, the helper now asks once more.

# Evaluation: keyboard and Back

**13/15 requests passed** across 3 runs of 3 conversations (2026-09-19). Before this round Jev could not press a key: every input went to a clicked element.

New operations: `PRESS_KEY` (Enter, Escape, the four arrows, Backspace, Tab: a fixed list owned by code, the key is a target like an element), `TYPE_KEYS` (letters typed into the page itself, for a page with no text field such as a word game; the text model supplies the word, code sends one key press per letter and accepts only letters, digits and spaces) and `GO_BACK` (the browser's Back, offered only when the tab has an earlier page). [`scripts/keys.py`](../scripts/keys.py) checks the page's own state: the game's score, the puzzle's locked-in rows, the address.

| Conversation | Request | Passed | Median time | Median decisions | What the check requires |
| --- | --- | --- | --- | --- | --- |
| 2048 (local fixture) | “play 2048 with the arrow keys until the score is at least 100” | 3/3 | 21.6 s | 30 | the game's own score is at least 100 (112 in 29 moves each run) |
| wordly.org | “guess the word crane” | 2/3 | 12.0 s | 5 | the first locked-in row is CRANE |
|  | “now guess slate” | 2/3 | 7.8 s | 5 | the second locked-in row is SLATE |
| Hacker News | “open the comments of the top story” | 3/3 | 3.7 s | 2 | a comment page |
|  | “go back to the front page” | 3/3 | 3.0 s | 2 | the front page again, and Jev reports done |

The 2048 board is a local, seeded page ([`scripts/fixtures/2048.html`](../scripts/fixtures/2048.html)): every public 2048 site now draws its board on a canvas, which Jev, reading text, cannot see. The miss on wordly.org: “crane” landed, but the page had not shown it when Jev looked, so the text model typed it again one letter at a time and the next guess went onto a spoiled row.

## Regression on the earlier evaluations

The same final code, rerun on the earlier suites: spoken answers **17/18** (the miss: the field-text model returned an empty reply twice before typing on coolblue.nl), conversations **23/30**. The conversation misses: “look up a picture of a cow” / “show me sheep instead” failed 0/6: Jev searched “cow images” and reported done on Google's ordinary results, which now show a strip of pictures, instead of opening Images. **The code from before this round (482407b) fails the same pair 0/6 on the same day**, so this is Google's results page changing since the first evaluation, not this round. The other miss: once “play the first video” opened a YouTube Short.

## What development turned up

- **Letters typed into wordly.org “never arrived”.** They did, but each letter pops in from opacity 0 and Jev read the page after 50 ms. After a key press Jev now waits until the page's finite animations end (at most 1.5 s).
- **Jev pressed “Arrow up” until the no-progress guard stopped it.** A key that changed nothing on a page is now withheld on that exact page, the way a declined map is. Rules also say a key that did nothing will do nothing again.
- **TypeSafe returned a near-tie (0.33 chosen beside 0.34)** and the validator rejected it as “not the top choice”. Probabilities come rounded to two decimals, so the chosen one may now be within 0.011 of the top.
- **Wikipedia's lead photo was a link named “link”** (no alt text). An otherwise unnamed control is now named by its image file (“image: Tour Eiffel Wikimedia Commons (cropped)”). Wikipedia's photo viewer was dropped as a test: whether a click opens the viewer or the File: page depends on its script's load timing.
- **Rules that tip DONE.** Every added sentence moved the balance between DONE and one more click on some page, so each change was checked by asking TypeSafe the same question several times on saved situations. Round 1's “a question is done once the page shows the answer” made DONE win on Google's web results for “cow images” (and was not needed: the weather result gets DONE at 0.99 without it), so it was removed. A “go back” rule made Jev return to Hacker News' front page after opening the comments it was asked for; `GO_BACK` is now described as only for requests that ask to go back, return or close.

# Evaluation: state that only colour carries

**No new operation.** This round is a change to what Jev sees. A page often says what something *means* only in its colour: a guessed letter marked right or absent, a field marked invalid, a calendar day marked unavailable. The characters already reached Jev; their state did not, so a scored Wordle board read as five bare letters.

`snapshot.js` now annotates visible text with the state its markup carries: class tokens and `data-state`/`data-status` matched against a vocabulary of state words, looking at the text's own element and at most two ancestors. A tile reads `c (absent)`. Nothing here is specific to a site or a game — the same code covers a rejected form field, a closed day, a status badge.

| Suite | Before | This round | Requests |
| --- | --- | --- | --- |
| [`scripts/conversations.py`](../scripts/conversations.py) | 23/30 | **23/30** | 3 runs of 10, median 5.0 s, median 3 decisions |
| [`scripts/answers.py`](../scripts/answers.py) | 17/18 | **18/18** | 3 runs of 6 |
| [`scripts/keys.py`](../scripts/keys.py) | 13/15 | **15/15** | 3 runs of 5 |

| Conversation | Request | Passed | Median time | Median decisions |
| --- | --- | --- | --- | --- |
| 2048 (local fixture) | “play 2048 with the arrow keys until the score is at least 100” | 3/3 | 16.5 s | 23 |
| wordly.org | “guess the word crane” | 3/3 | 7.1 s | 3 |
|  | “now guess slate” | 3/3 | 9.4 s | 5 |
| Hacker News | “open the comments of the top story” | 3/3 | 3.1 s | 2 |
|  | “go back to the front page” | 3/3 | 2.9 s | 2 |

Both wordly.org misses from the previous round are gone. The plausible reason is that a landed guess now looks different from an empty row, so the text model no longer retypes a word the page had already accepted — but 15 requests is a small sample and 13/15 → 15/15 is not on its own proof of cause.

The conversation total is unchanged, failure for failure: “look up a picture of a cow” / “show me sheep instead” 0/6 (the same Google drift the previous round measured against `482407b`), plus one “play the first video”.

## What this round does not show

Jev is not shown here *using* the feedback. Wordle and Globle put every earlier guess on screen, so reading them tests observation, not learning: no check here requires a second guess to respect what the first revealed. Nothing carries between pages either — the field helper gets the current page's text and the last six actions, so a fact read on one page is gone by the next. Both are open.

## What development turned up

- **A word describing the container is not the thing's own state.** wordly.org marks a submitted row `Row-locked-in` while its tiles are still flipping. Annotating a colourless tile `(locked)` from its row stated a fact the page had not settled, so `locked` is deliberately absent from the vocabulary: a bare letter honestly reads as “no feedback yet”, a wrong state reads as fact. The ancestor walk stops after two levels for the same reason — a page-level wrapper marked `active` must not annotate every word on the page.
- **The flip is slow and staggered.** Four seconds after Enter a real board is still only part-scored, so observing straight after a key press yields a half-read board. The existing `wait` control covers it; nothing yet tells Jev to use it.
- **The annotation is quiet in practice.** Measured on the suites' own sites: 2 annotations on the whole Eiffel Tower article, 0 on Hacker News, Google results, YouTube and nu.nl. The feared noise from `active`/`current` on navigation links did not appear.
- **Two providers spell reasoning differently.** The field helper returned nothing on roughly one call in forty. It was not the model failing: reasoning tokens were filling the 1024-token window until the reply came back truncated and null. Inception's own API honours `reasoning_effort` and silently ignores OpenRouter's `{"reasoning": {…}}` object, so the switch that was meant to be off was on. With `reasoning_effort` the same model answers in 50 tokens instead of 1022. Each helper now resolves its own endpoint, so the field model can sit on one provider while the answer and map models sit on another.

# Evaluation: a stopped run says what it reached

**No new operation.** This round changes what happens when a run *ends*. `spoken_answer` ran only on `DONE`; every other ending — the model's own `BLOCKED`, a loop guard, a refused target, the step budget — spoke app.js's fixed “I got stuck after N seconds” with no model call at all, so a game played to its last round never read out the score that was on the screen. `report()` now runs at every terminal stop and the answer model is told whether the run `finished` or `stopped`. Two smaller changes ride along: a target the executor refuses on a page that did not change is withheld from the next choice (a rejection executes nothing, so no history entry records it and an unchanged page returns the same choice forever), and `NEXT_ACTION` gained two sentences — Enter submits a filled field whose submit control is missing, and a round-based task the page shows as over is `DONE`, never `BLOCKED`.

| Suite | Previous round | This round | Requests |
| --- | --- | --- | --- |
| [`scripts/conversations.py`](../scripts/conversations.py) | 23/30 | **20/30** | 3 runs of 10, median 5.0 s, median 3 decisions |
| [`scripts/answers.py`](../scripts/answers.py) | 18/18 | **18/18** | 3 runs of 6 |
| [`scripts/keys.py`](../scripts/keys.py) | 15/15 | **13/15** | 3 runs of 5 |

Both drops were measured, not explained away, and neither one is this round's code.

**The conversation drop is YouTube, and the previous commit fails the same way today.** All three of this round's extra misses are in the YouTube conversation, where “play the first video” now opens a Short. Rerunning that conversation alone on `97298cc`, the commit this round builds on, on the same day against the same site:

| YouTube conversation, 2026-09-20 | `97298cc` (previous round) | This round |
| --- | --- | --- |
| “go to youtube.com and search for the moon landing” | 3/3 | 3/3 |
| “play the first video” | 0/3 | 1/3 |
| “open the channel of this video” | 1/3 | 1/3 |
| total | **4/9** | **5/9** |

Every one of those six runs, on both commits, landed on the same Short (`youtube.com/shorts/YTCXN5qVAOA`), which the check rejects because it requires `youtube.com/watch`. The previous commit is one request *worse* today than this one, so the 23/30 → 20/30 move is the site, not the change; at nine requests the 4/9 → 5/9 difference is noise and is not claimed as an improvement either. A follow-up also inherits the page the request before it ended on, so one wrong turn costs two requests: “open the channel of this video” then opens a Short's channel.

The images pair still fails 0/6, as it did last round, but twice by a new route: instead of stopping on Google's ordinary results, Jev left Google for `pngtree.com` and was stopped by a Cloudflare verification screen.

**The keys drop is wordly.org's known flakiness.** Its pair failed in the first of the three runs (four `TYPE_KEYS` in a row, no Enter, blocked) and passed in the other two. Three further wordly-only runs on this same code passed 6/6, putting the site at 10/12 here. The previous round measured 6/6 and the round before that 4/6 on a key path this round does not touch, and that round's own write-up already said 15 requests was too small to call 13/15 → 15/15 proven. It is not evidence of a regression, and 10/12 is not evidence the flake is gone.

| Conversation | Request | Passed | Median time | Median decisions |
| --- | --- | --- | --- | --- |
| Google news | “look up the latest news about the war in Yemen” | 3/3 | 6.0 s | 3 |
|  | “play the video” | 3/3 | 3.5 s | 3 |
| Hacker News | “go to news.ycombinator.com and open the comments of the top story” | 3/3 | 3.5 s | 2 |
| YouTube | “go to youtube.com and search for the moon landing” | 3/3 | 5.3 s | 6 |
|  | “play the first video” | 1/3 | 3.0 s | 2 |
|  | “open the channel of this video” | 1/3 | 5.8 s | 6 |
| Wikipedia | “find the Wikipedia article about the Eiffel Tower” | 3/3 | 7.0 s | 4 |
|  | “now open the article about the man who designed it” | 3/3 | 3.4 s | 2 |
| Google Images | “look up a picture of a cow” | 0/3 | 6.4 s | 4 |
|  | “show me sheep instead” | 0/3 | 4.3 s | 3 |

## What this round does not show

**No suite checks the thing this round adds.** `conversations.py` and `keys.py` record where a run ended, not what it said; `answers.py` checks the spoken sentence but counts a request only when its status is `done`, so every sentence this round introduced — the ones a *stopped* run speaks — is outside all three. Eight unit tests pin the behaviour offline. The only live evidence is observational: asked to look up a picture of a cow, a run that ended `blocked` on a Cloudflare screen said *“I got as far as navigating to a page for cow images on Pngtree, but was blocked by a Cloudflare security verification screen. I was unable to load and display the pictures.”* where it would previously have said “I got stuck after 9 seconds.” That is one example, not a measurement. A suite that scores what a stopped run says is the obvious next piece of work.

**A stopped run now costs one more model call.** Every ending that is not `DONE` adds an answer-model call (about $0.0014 at `google/gemini-3.8-flash`). Runs that finish are unchanged.

## What development turned up

- **The measurement harness dies on an emoji.** One request per suite run ends with `UnicodeEncodeError: 'charmap' codec can't encode character` when a page label or answer containing an emoji is printed to a Windows console. It predates this round — `round3-2` and `round3-3`, measured on `97298cc`, carry the same error — and it is a printing failure in the script, not in the loop: the request it kills is still checked on its final page, and it passed in this round's run 1. Left alone here so this round stays one change.
- **A follow-up multiplies a wrong turn.** Because each request continues from the page the last one ended on, the YouTube Short cost two requests rather than one. This is by design and worth remembering when reading a conversation total: ten requests are not ten independent samples.

## Two contained fixes after this round

Both are corrections to the round above, measured separately from it so the cause of any move is unambiguous.

**A run could be silently unable to speak.** `report()` asked whether `TEXT_MODEL_API_KEY` was set, but the answer helper resolves `ANSWER_MODEL_API_KEY`, then `HELPER_API_KEY`, then `TEXT_MODEL_API_KEY`. A configuration naming only `HELPER_API_KEY` — which `helper_endpoint` documents as sufficient, and which `.env.example`'s one-provider setup encourages — therefore said nothing at all, on every ending, with no error. The gate now asks `helper_key("ANSWER_MODEL")`, the same question the call asks. The measured configuration here sets `TEXT_MODEL_API_KEY`, so this appears in no number; four tests cover it.

**One control clicked over and over now stops the run.** `from_view` hashes the page text along with the action, so a control that re-renders the page on every click — a recommendation filter, a “load more” that replaces the list — looks like a new situation each time and `CYCLE_REPEATS` never fires. The recorded case is a run that clicked “From Dutchsteammachine” eight times. An unbroken run of five identical **clicks** now ends the request as `blocked`, which the answer helper then reads out. Only clicks: a game presses one arrow all game, a puzzle types letter after letter, and a map plays round after round through the same Next button.

The threshold is measured rather than chosen. Across every run recorded under `artifacts/`, counting the longest unbroken run of identical consecutive clicks in each request:

| Longest identical click run | Requests | Outcome |
| --- | --- | --- |
| 2 | many | the only length ever reached by a request that **passed** |
| 3–4 | 7 | all failed (Al Jazeera's empty player, `ns.nl`, Hacker News) |
| 5 | 1 | failed (`ns.nl`, “Vertrek Nu”) |
| 8 | 1 | failed (YouTube, “From Dutchsteammachine”) |

So five is below every observed failure of this shape and above every observed success. It is still a containment change and nothing more: it cannot turn a failing request into a passing one, because a target clicked five times is not the target the request needed.

| Suite | The round above | With both fixes | Requests |
| --- | --- | --- | --- |
| [`scripts/conversations.py`](../scripts/conversations.py) | 20/30 | **20/30** | 3 runs of 10 |
| [`scripts/answers.py`](../scripts/answers.py) | 18/18 | **6/6** | 1 run of 6 |
| [`scripts/keys.py`](../scripts/keys.py) | 13/15 | **5/5** | 1 run of 5 |

The conversation total is identical, failure for failure: the images pair 0/6 (now by leaving Google for `pngtree.com`), “play the first video” 0/3 on the same Short, “open the channel of this video” 1/3. **The new guard did not fire once** in those 30 requests, nor in the 11 of the other two suites — which is the expected result for a bound on a shape that only appears when a request is already lost. The `answers` and `keys` figures are single runs, run to confirm nothing broke; they are not three-run measurements and the `keys` 5/5 says nothing new about wordly.org's flake.

# Evaluation: a site named without its address

**Where this came from.** A user asked *“On GitHub: find jkudish/jev-browser, open Releases, stop on the newest”*. The first run stopped on an empty Google page (*“I got as far as the Google homepage, but I was unable to navigate to GitHub”*); the same request, asked again straight after, finished on the release list. Rerun fresh from Google on `b41538a`, the commit before this round, it failed **3 out of 3**, each time the same way.

**Why the first run failed.** Four steps, each needed for the next:

1. The request names GitHub but not `github.com`, so it starts on Google, and the text helper typed the bare name `jkudish/jev-browser` (6 of 6 in a probe). Google's first screen of results for that has no GitHub link: an AI-skill directory, three YouTube videos and *“Did you mean: kudish/web-browser”*. The repository is indexed; it ranks below them.
2. `WEB_SEARCH` was offered on those results. It was hidden only on the exact start address `https://www.google.com/?hl=en`, so a results page counted as “another site”, and its label said *“google.com's own search box only finds google.com content”*. With no GitHub link in view the model took it (probability 0.42–0.55) and went back to an empty Google page.
3. There it clicked **Google Search** under the now empty field three times. Nothing changed, and the unchanged-page guard ended the run. In another run it retyped the same query, got the same results, took `WEB_SEARCH` again, and the cycle guard ended it.
4. The spoken answer read the empty page correctly, which is how the user heard where it stopped.

**Why the second run worked.** No code differed. Asked again, the request was a follow-up, and its goal carried the first attempt marked *(not finished)*. With that context the text helper added “github” to the query (4 of 6 in the probe, against 0 of 6 fresh). Google then lists the jkudish profile first, a GitHub link was in view, and the model clicked it (0.77, against 0.15 for `WEB_SEARCH`). It was chance, not a recovery.

## What changed

- **`WEB_SEARCH` is not offered on Google's own search pages** (`/`, `/search` and `/webhp` on any `google.*` domain). They already search the whole web; leaving them only swaps the results for an empty page. It is still offered everywhere else, Google Flights included. `WEB_SEARCH` was never chosen in any of the 635 requests recorded before this round, so no earlier number can move because it is gone.
- **A web search for a request that names a site carries the site's name** (one sentence in `TEXT_VALUE`), and a site's own search box never does. Probed with the text helper, 10 samples per field on live pages: the fresh GitHub request named GitHub 10/10 (was 0/6), as `on GitHub`, `GitHub` or `site:github.com`, all three of which put a GitHub link first. YouTube's and Coolblue's own boxes, the word game, and the Yemen news, cow and weather queries were unchanged, and the Wikipedia query was already `Eiffel Tower Wikipedia` most of the time.
- **A click that changed nothing is not offered again on that page**, as a key already was not. The search button under an empty field is now clicked once, then withheld.
- **A control's own `<style>` is not part of its name.** Google's **AI Mode** button carries one, so every Google page listed a link named `.plR5qb.PHjFye .CcxW7b{display:none}…`.

Fixing Google took the request to GitHub every time, and then **3 of 5** runs passed. The two failures showed that Jev read GitHub's pages before they had finished arriving, in three separate ways, all fixed in `browser.py`:

- **A new tab was read while still blank.** This Chrome profile has Google's “open each result in a new window” setting, so a result opens a new tab, and a new tab is `about:blank`, and “complete”, until the link's page commits. One run chose `DONE` on the blank page and had it accepted before the page arrived. A new tab is now read once it has left `about:blank` (at most 5 s).
- **The repository page was read before its sidebar.** GitHub loads the page with skeleton placeholders and replaces them over about a second, and the Releases link comes last. Read after the old 150 ms quiet rule, the page had no Releases, and three runs clicked **Activity**, the nearest link, one of them never recovering. The page is now read once its placeholders have stopped being replaced (at most 3 s). A replacement is what counts, because YouTube shows placeholders that are never replaced: masthead icons, and an empty grid on the home page.
- **A click inside GitHub was read before its page came.** GitHub's navigation marks the page `aria-busy` for about half a second before it changes the address. Read in between, the old page looked unchanged, and the next choice was made on it and refused. A visible `aria-busy` now counts as still loading.

Checked without any model call, by clicking the way Jev does and reading the page it reads:

| Jev's first read after the click | `b41538a` | This round |
| --- | --- | --- |
| Into the repository from the profile's list: Releases present | 0/6 | **8/8** |
| Releases, on the repository page: the release list read | 0/8 | **8/8** |

## The request itself

| Code | Runs from Google | Ended on the release list or the release marked Latest |
| --- | --- | --- |
| `b41538a` | 3 | **0/3** |
| Google-side changes only | 5 | **3/5** (one `DONE` on a blank tab, one stop on the Activity page) |
| This round | 5, the user's own wording | **5/5**, median 16.5 s |
| This round, in `conversations.py` | 3 | **3/3**, median 15.7 s, median 9 decisions |

The request is now the sixth conversation in [`scripts/conversations.py`](../scripts/conversations.py), checked by the final URL: the repository's release list, or a release page GitHub marks **Latest**.

## Regression on the earlier evaluations

| Suite | Previous round | This round | Requests |
| --- | --- | --- | --- |
| [`scripts/conversations.py`](../scripts/conversations.py), the ten requests measured before | 20/30 | **28/30** | 3 runs, median 5.6 s, median 3 decisions |
| the GitHub request, new | — | **3/3** | 3 runs, median 15.7 s |
| [`scripts/answers.py`](../scripts/answers.py) | 18/18 | **18/18** | 3 runs of 6 |
| [`scripts/keys.py`](../scripts/keys.py) | 13/15 | **15/15** | 3 runs of 5 |

No request ended in an error, so this is also the first three-run measurement of `7bf6d59` (a label the console cannot show no longer ends a request) and `b41538a` (five scrolls in a row stop a run), both committed unmeasured. The scroll guard fired once, on a request already lost (below).

| Conversation | Request | Passed | Median time | Median decisions |
| --- | --- | --- | --- | --- |
| Google news | “look up the latest news about the war in Yemen” | 3/3 | 6.0 s | 3 |
|  | “play the video” | 3/3 | 3.2 s | 3 |
| Hacker News | “go to news.ycombinator.com and open the comments of the top story” | 3/3 | 3.3 s | 2 |
| YouTube | “go to youtube.com and search for the moon landing” | 3/3 | 5.1 s | 5 |
|  | “play the first video” | 2/3 | 3.4 s | 2 |
|  | “open the channel of this video” | 2/3 | 8.7 s | 7 |
| Wikipedia | “find the Wikipedia article about the Eiffel Tower” | 3/3 | 7.3 s | 4 |
|  | “now open the article about the man who designed it” | 3/3 | 3.1 s | 2 |
| Google Images | “look up a picture of a cow” | 3/3 | 7.3 s | 4 |
|  | “show me sheep instead” | 3/3 | 7.0 s | 3 |
| GitHub | “On GitHub: find jkudish/jev-browser, open Releases, stop on the newest” | 3/3 | 15.7 s | 9 |

**The eight extra passes are two conversations, and only one is plausibly this round's work.**

- **YouTube is the site.** Its first result for the moon landing was a `/watch` video in two runs and the same Short as last round (`youtube.com/shorts/YTCXN5qVAOA`) in the third. That Short fails the check, and the follow-up *“open the channel of this video”* started from it, scrolled the Shorts feed five times, and was stopped as `blocked` by the scroll guard. Last round the Short came first in two of the three runs. Nothing this round changed decides which result YouTube ranks first.
- **Google Images went 0/6 → 6/6 by a new route, most likely the label fix.** Last round Jev typed first (`cow images`) and ended on ordinary results or on `pngtree.com`. This round its first move on Google's home page was the **Search for Images** link, in all three runs. That first decision sees one difference: the AI Mode button's label, which was a line of CSS. Asked that first decision on the same live page, TypeSafe typed first 6 times out of 6 with the old label and clicked **Search for Images** 4 times out of 6 with the new one. That is six samples each on one page; it makes the label fix the likely cause, and Google's own page may still have changed.

**Slower where a page is filling itself in.** The new wait was A/B tested by loading each page five times with the old and the new code in alternation. Google's results, Hacker News, a YouTube watch page and nu.nl showed no difference beyond network noise (±0.5 s either way). **YouTube's home page is 0.66 s slower on every load**: its loading skeleton is replaced by the app, which starts the wait, and the grid of placeholders that follows stays, so the wait runs its full second. That is one load per conversation that starts on youtube.com. The GitHub repository page is about 0.2–0.3 s slower, which is the point. The median request rose from 5.0 s to 5.6 s, mostly because more requests now go further: the images pair and the YouTube channel request pass, and take more steps doing it.

## What this round does not show

- **The page-filling wait is a heuristic measured on GitHub alone.** It looks for `aria-busy` and for “skeleton” in a class name. A site whose placeholders are named otherwise, or that fills in after 3 s, is still read early, and the model then picks the nearest control, as it did here.
- **The query rule rests on one live request.** It was probed on nine fields offline. Live, only the GitHub request exercises it, plus the Wikipedia request, whose query already named Wikipedia most of the time.
- **Google's ranking of this repository will change.** As `jkudish/jev-browser` gains links, the bare-name query may start listing it first, and the GitHub conversation will then pass without testing the query rule at all.
- **Five and three runs are small.** 0/3 → 5/5 on the request itself is a clear direction, not a rate.

## After this round: the answer is not the run's time

**What the user saw.** A run of the GitHub request finished in a few seconds, and then the inspector's clock kept running for about 15 s, until the console printed `ANSWER helper: None — 14824 ms`. Every run ends with one call to the answer model, which decides whether the request asked something to say out loud. This request did not, so `None` was right, and the call was a formality. But the run's time was only set, and the inspector's clock only stopped, once that call came back.

**Why the call took 15 s.** Not the model: the same call, repeated, always came back as 10 tokens with no reasoning. OpenRouter serves `google/gemini-3.8-flash` from two Google providers, and either one sometimes stalls:

| Routing of the answer call | Calls | Over 5 s | The slow ones |
| --- | --- | --- | --- |
| OpenRouter's own choice, as shipped | 79 | 3 | 12.5–12.6 s, all in one early burst and all finished by the fallback provider |
| Google Vertex only | 11 | 3 | 7.9 s, 8.1 s, and one still waiting at the 25 s client timeout |
| Google AI Studio first | 50 | 2 | 7.2 s and 9.7 s, served by AI Studio itself |

Asking OpenRouter to try AI Studio first was built, tested and then removed. In the first 20 AI Studio calls none stalled, but a 30-and-30 A/B alternating with the shipped routing gave AI Studio 2 stalls and the shipped routing none. The stalls come in bursts and hit both providers, so nothing in the table shows the pin helps.

**What changed instead.** A run's own time no longer includes the answer. `report()` sets `elapsed_ms` when the run stops. With `Agent(answer_later=True)`, which the inspector uses, the answer waits for a separate `answer` command. `app.js` stops its clock at the stop, shows *“reading the page for an answer…”*, and asks for the answer as its own request. A voice run still speaks only when the answer is in, and its "Done in N seconds" counts the run, not the answer. The library and the suites keep one call that returns with the answer, as before. Their times are their own wall-clock measurements, so no suite number can move.

Checked in the real inspector page, driven by a script: the GitHub request's clock froze at **40.6 s** at `DONE`, the status read *“Jev reports complete · reading the page for an answer…”*, and the answer, another slow one, landed **6.7 s** later without moving the clock. Four tests pin it and fail on the previous code.

**What this does not fix.** The slow answer call still happens: 5 of the 129 calls above that were not pinned to Vertex took over 5 s. The spoken reply, or the word "Done", still waits for it; only the time shown and reported stops counting it.

## After this round: a second request for a stalled answer

**Where the stall comes from.** OpenRouter's own record of each call (`/api/v1/generation`) lists every provider attempt and Google's `service_tier`. In two batches of the same answer call, about half ran on capacity reserved for OpenRouter (`provisioned`, 18 of 18 under 2.3 s) and half on Google's shared pool (`default`), where every long wait happened. A call on the shared pool either waited 5–11 s before its first token (the ten-token reply then took 0.1 s), or was cut off by Vertex with a 504 after 11.5 s and retried at Google AI Studio, about 13 s in all. The user's 14.8 s had that second shape. Nothing in the request chooses the tier.

**What changed.** `hedged()` in `model.py`: when a spoken answer has not come back after 4 s, a second copy of the same request is sent, and whichever answers first is used. That is safe because the call only reads. 4 s sits above every unstalled answer measured, 1.4–3.8 s including real questions (Utrecht weather, the Eiffel Tower's height), and well below the stalls. Each copy borrows a client of its own, because parallel requests through one shared HTTP/2 client had failed 2–3 times in 90. The console says when an answer was asked twice. Only the spoken answer is hedged: the text helper runs on Inception, where no stall was seen, and map calls were not measured.

| 50 alternating calls each, same finished-run context | Median | p90 | Slowest | Over 5 s | Second copies |
| --- | --- | --- | --- | --- | --- |
| One request, as before | 1.56 s | 2.46 s | **13.2 s** | 2 | — |
| Second copy after 4 s | 1.57 s | 2.55 s | **5.9 s** | 2 (5.6, 5.9 s) | 3 |

The median does not move, and a stall now ends at about 4 s plus one normal reply. The price is the extra requests, 3 in 50 here, about $0.0015 each.

**Not fixed.** One call in the hedged arm failed in 2.9 s, before any second copy: OpenRouter replied *“google/gemini-3.8-flash is temporarily rate-limited upstream”*, a limit on its shared Google capacity, and the helper's one retry met the same. The run then says it could not read out what happened. It can happen with one request as well, and is not handled here. Separately, this account is held to 20 requests a minute for this model; one answer per run stays far below that.

## After this round: a live countdown does not stale every decision

**Where this came from.** On JetPunk's *Black Sea Countries* quiz, Jev repeatedly refused its own decisions:
`DONE` became *“Page changed since the decision”*, and the answer textbox became *“Page changed before text
generation”*. A read-only pair of snapshots from the user's open Chrome tab isolated the change: visible text went
from `2:00 (active)` to `1:59 (active)`, while the page key, every form value, and the textbox's identity/state guard
were identical.

**What changed.** Text fields now use their target-specific freshness guard before the text helper as well as at
execution. A terminal decision still checks the whole page, but a standalone active countdown tick is normalized;
all other visible text, controls, field values, identity, URL, viewport and scroll position remain significant. A
Chrome renderer swap seen during a cross-document Back navigation is also treated as the transient stale read it is,
so the existing retry loop can finish instead of failing the guard suite.

**Measured on the reported page, in the same Chrome profile.** Across a real `2:00` → `1:59` tick, both terminal
freshness and textbox freshness returned true. Six answers were then entered through `Browser.act`, deliberately
crossing countdown ticks. JetPunk settled on its independently read scoring page at **6/6 = 100%**, with all six
countries marked correct and no textbox remaining. This verifies the guarded browser path, not TypeSafe's ability to
discover those six answers. The offline suite is **145/145**, and the local-browser suite is **28/28**, including a
fixture that accepts only the active countdown change and still rejects ordinary visible-text changes.

## After this round: one positional recommendation click is one action

**Where this came from.** On JetPunk, the request *“click on the quiz in the recommended quizzes that on the
right the most upper one”* did not terminate after opening a quiz. A captured run made **20 clicks**: it alternated
between two quiz URLs and interleaved **Start Quiz**, until the 20-action budget stopped it. The existing repeated
click guard did not apply because the labels alternated. The view-cycle guard did not apply because each running
quiz's timer changed the page text used by its fingerprint.

**What changed.** A request that is literally one click (including polite forms such as “please click” and “could
you click”), with no `and`/`then`/`after`/`before`/`also` continuation, finishes in code after its selected click
changes the page. This uses TypeSafe's selected observed target and the executor's independently observed page
change; it does not ask TypeSafe to recognize `DONE` on a destination that contains another similar list. Compound
requests continue normally. As containment for other changing-page loops, the same named click traversing the same
source URL → destination URL three times now stops the run.

The target policy also receives each observed element's rounded `left` and `top` screen coordinates. Previously it
saw labels and linear page text but no geometry, so “top right” was not grounded. On the live destination page,
without coordinates the first exact run selected the lower **Largest World Cities With Seven Letters** link. With
coordinates, ten repeated target decisions selected the uppermost other quiz, **Which Letter Has the Highest
Population?**, **10/10**.

**End-to-end on the user's existing JetPunk target.** The exact request clicked **Which Letter Has the Highest
Population?**, changed from the *Largest World Cities With Seven Letters* URL to that quiz's URL, and returned
`done` after **one action**. The offline suite is **151/151**; the local-browser suite remains **28/28**.
