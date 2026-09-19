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
