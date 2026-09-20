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
