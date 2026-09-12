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

## Open questions

- Should the status-line collector ship as a required install step, or
  degrade silently to "no runway, tokens only" when absent?
- Is the RE `oauth/usage` endpoint worth adopting as a `--online` opt-in
  fallback given its rate-limit fragility?
