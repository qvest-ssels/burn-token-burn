# ADR-0002: Claude Code adapter

- **Status:** Accepted (2026-09-05, adapter implemented)
- **Date:** 2026-09-05

## Context

Claude Code writes per-session JSONL transcripts to
`~/.claude/projects/<project>/<session>.jsonl`, plus one file per
sub-agent under `<session>/subagents/agent-*.jsonl` — each sub-agent may
run its own model (e.g. Haiku doing markdown polish while the main loop
runs a larger model). A coarse `stats-cache.json` also exists but isn't
granular enough to replace the transcripts. Transcripts are retained only
for `cleanupPeriodDays` (observed ~30 days).

Each `type == "assistant"` line carries `message.usage{input, output,
cache_creation_input_tokens, cache_read_input_tokens,
cache_creation.ephemeral_5m/1h}` and `message.model`. Claude Code writes
**one JSONL line per content block**, so one API response appears
multiple times — dedup is mandatory. Verified composite key:
`(message.id, requestId)`; without it, this repo's own dogfooding session
had 371 lines collapse to 197 real API calls (~1.9x over-count).

Anthropic subscriptions publish no token counts against a budget. The only
budget concept is **opaque rolling percentages**: a rolling 5-hour window
and a rolling 7-day window (plus, on some plans, a weekly Opus/Sonnet
sub-limit and extra-usage dollars). Remaining quota is **not derivable
from local transcripts** — those show only what was *done*, not what is
*left*. Two sources give the real percentage: (1) officially, the
status-line JSON payload (`statusLine.command`) carrying
`rate_limits.five_hour/seven_day{used_percentage, resets_at}` on Pro/Max —
pushed, not polled, so it needs our own collector; (2) a
reverse-engineered `GET api.anthropic.com/api/oauth/usage` call, bearer
token from `.credentials.json`/Keychain, heavily 429-rate-limited.

## Decision

**Full adapter.** Parse the JSONL transcripts (including `subagents/`),
dedup on `(message.id, requestId)`, normalise token fields, and estimate
USD via the LiteLLM price snapshot for "what did this cost". For the
runway — "how much is left" — treat the local sum as descriptive only,
sourcing the authoritative `QuotaSnapshot` from a status-line collector
(`token-finops collect-statusline`) persisting `rate_limits` into
`~/.token-finops/quota.json`. The RE `oauth/usage` endpoint may be added
later as a fallback for users without the collector wired up.

**Compaction (T-15).** Mid-session compaction (main loop or a Cowork cloud
session) starts writing a *new* transcript file that carries the *same*
`sessionId` as the segment being compacted away. `scan()` already globs
every `*.jsonl` recursively under `projects/`, so `self-audit` groups events
from every such segment under one session id; it additionally dedups the
combined set by `event_id` (a segment boundary could in principle re-emit an
event) and reports how many distinct main-transcript files it stitched as
`segments: N` in the header, so a dogfooding run split by compaction reads
as one number instead of two unrelated `self-audit` runs.

## Consequences

**What we get:** full token/model/sub-agent attribution locally, a
credible USD-equivalent, and — once the collector runs at least once — a
real rolling-window runway sourced from Anthropic's own numbers instead of
a guess.

**Robustness:** The adapter handles garbage appended to JSONL files (truncated
records, invalid JSON) by preserving all intact events, tolerates binary bytes
in transcript content by replacing them rather than raising, and normalizes
various timestamp formats (ISO 8601, with/without timezone) to UTC. Drifted
quota file shapes (missing or unexpected fields) are handled defensively.
Corrupt or unreadable transcript files are skipped silently, leaving intact
sessions still queryable.

**Risks:**
- Schema drift: JSONL field names have already shifted across versions;
  alias lists and skip-on-parse-failure are required.
- The RE `oauth/usage` endpoint is unversioned and rate-limited (429s);
  must never be polled eagerly.
- Sub-agent double-counting if dedup keys are misapplied, or a
  sub-agent's tokens are also reflected in a parent summary line.
- Privacy: transcripts hold full conversation content; the adapter must
  only ever extract usage metadata, never log message bodies.
- 5h/7d percentages have no fixed absolute denominator, so cross-tool
  roll-up must treat this as percent-of-window, not tokens/dollars.

## Alternatives considered

- **ccusage** — most mature (Rust core), 5-hour block detection, LiteLLM
  pricing; we adapt its algorithms in Python rather than depend on it.
- **Claude Code Usage Monitor**, **ccburn**, **claude-usage**,
  **CodeBurn**, and menu-bar/taskbar variants — close to "runway" but
  none normalise across tools; listed in `docs/landscape.md`.

## Online fallback (T-03, 2026-09-22)

The `oauth/usage` fallback anticipated above now exists, strictly as an
opt-in: `token-finops report|status --online` sends `GET
api.anthropic.com/api/oauth/usage` with `anthropic-beta:
oauth-2025-04-20` and a bearer token read (never written, never
refreshed) from `~/.claude/.credentials.json`, yielding a `QuotaSnapshot`
with `source="claude_oauth_usage"` — distinguishable at a glance from the
collector's `claude_statusline`. The response shape is undocumented, so
the parser accepts `five_hour`/`fiveHour`/`5h` (and the `7d` twin) and
reads the utilisation either as a percentage or as a 0–1 fraction.

**The status-line collector remains the supported source.** This path is a
fallback for users who have not wired the hook (or whose session is not
running under Claude Code at all), not a replacement: the endpoint is
reverse-engineered and hands out 429s freely, which is exactly why the
response is cached >= 180 s in `~/.token-finops/online-cache.json` —
*including failures*, so a polled status bar retries at most once every
three minutes instead of on every redraw. A 429, an expired token, a
Keychain-only install with no `.credentials.json`, or a drifted body all
fail closed to the existing offline behaviour with no error shown.

## Open questions

- Should the status-line collector ship as a required install step, or
  degrade silently to "no runway, tokens only" when absent?
- ~~Is the RE `oauth/usage` endpoint worth adopting as a `--online` opt-in
  fallback given its rate-limit fragility?~~ Answered by T-03 (see above):
  yes, opt-in, cached, and fail-closed — but as a fallback behind the
  collector, never as the primary source.
- macOS keeps the OAuth token in the Keychain on some installs, where
  `.credentials.json` does not exist. Is shelling out to `security
  find-generic-password` acceptable, or does that cross the line from
  "read a file" into "operate the user's credential store"?
