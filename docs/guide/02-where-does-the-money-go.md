# 02 — Where Does the Money Go?

The honest way to answer this is to point a tool at a real session and count. We ran `token-finops self-audit` against the transcript of the Claude Code session that built this repository — a month-long span, 488 deduplicated API calls (226 in the main loop, 262 across seven sub-agents), 83.5 million total tokens. Here is exactly where that went.

## Cache reads are 95% of tokens, priced at 10%

| Category | Tokens |
|---|---|
| Input | 1.9k |
| Output | 256.4k |
| Cache read | 79.5M |
| Cache write | 3.7M |
| **Total** | **83.5M** |

Cache reads alone are 79.5M of 83.5M tokens — over 95% of everything counted. This is normal for an agentic coding session: every turn re-sends the accumulated conversation and file context, and prompt caching means most of that re-send is billed at roughly a tenth of the fresh-input price rather than full price. That 10x discount is the single biggest reason a 171k-tokens-per-call session doesn't cost what the raw token count implies — but it also means raw token counts are a nearly useless proxy for cost. A session that "used 80 million tokens" sounds enormous; priced correctly, this one came to $97.70 in API-equivalent terms. The lesson: don't budget or panic based on token counts alone — price them.

Cache *writes* cut the other way. Anthropic bills a 1-hour cache write at roughly 2x the normal input price, because you're paying to populate a cache you may or may not reuse enough times to amortize that premium. 3.7M tokens of cache writes in this session is small next to 79.5M of reads, which is the shape you want — if writes and reads were closer to parity, the caching strategy would be closer to a wash than a win.

## Duplication is a parsing problem, not a usage problem

Claude Code's JSONL transcripts write one line per content block, not one line per API call — a single assistant turn with three tool calls shows up as three lines. Counting lines instead of deduplicating on `(message.id, requestId)` over-reports by roughly 1.8–1.9x. This session's earlier line count was 371; deduplicated, it was 197 actual messages. This isn't a cost driver in the sense of money actually spent, but it's the single most common way people misdiagnose their own spend — "it used 80M tokens" measured from raw lines can silently be double or triple the real number.

## Sub-agents cost against the same clock, at a different rate

Sub-agent calls aren't free extras — they draw from the same 5-hour and 7-day rolling window as the main loop, frequently on a more expensive model than the developer would have chosen by hand. In this session, sub-agents accounted for 262 of 488 calls and roughly 30% of total API-equivalent cost. Three research sub-agents alone, all running on the frontier model, cost more combined than every Sonnet-tier call in the entire session — main loop and sub-agents together. If you're not watching sub-agent spend specifically, you're not watching the part of the bill most likely to surprise you.

## Model choice dominates everything else

| Model | Calls | Cache r/w | API-eq $ | Share |
|---|---|---|---|---|
| claude-fable-5-1 | 270 | 46.1M / 1.7M | $82.76 | 85% |
| claude-sonnet-5 | 217 | 33.3M / 2.0M | $14.94 | 15% |

Fable ran 270 of 488 calls (55%) but generated 85% of the API-equivalent cost. Sonnet ran nearly as many calls — 217 — for 15% of the cost. That gap, roughly 5.5x per call on average, is bigger than any caching optimization or dedup fix could ever produce. Retries and agent loops (a tool call that fails and gets retried, a sub-agent that re-derives context because it didn't get handed the parent's cache) add real waste on top of this, but they're rounding error next to the plain fact that which model answers the call decides the bill more than anything else you could tune. That's the subject of the next chapter.

You don't have to take our numbers for it: `token-finops burn --efficiency` runs this exact breakdown against your own transcripts — cache hit ratio, frontier-tier share, sub-agent share, and the routing dividend (what mixing in a cheaper model actually saved versus running everything on the most expensive one in the mix). See `docs/BURN.md` for the formula behind each figure and its caveats.
