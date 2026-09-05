# ADR-0003: OpenAI Codex CLI adapter

- **Status:** Proposed
- **Date:** 2026-09-05

## Context

Codex CLI writes rollout transcripts to
`${CODEX_HOME:-~/.codex}/sessions/YYYY/MM/DD/rollout-*.jsonl`, with older
sessions moved to `archived_sessions/`. Session metadata lives in
`type == "session_meta"` (`payload.id`, `payload.cwd`); model selection in
`type == "turn_context"` (`payload.model`).

Token usage is emitted as `type == "event_msg"` with
`payload.type == "token_count"`, carrying
`payload.info.total_token_usage{input_tokens, cached_input_tokens,
cache_write_input_tokens, output_tokens, reasoning_output_tokens,
total_tokens}`. This total is **cumulative per session**, so usage events
must be emitted as deltas between consecutive rows; duplicate rows with an
unchanged total exist and must be skipped, and a fallback to
`last_token_usage` is needed when the cumulative field is absent.
`input_tokens` already includes `cached_input_tokens` (cache-read must be
subtracted out), and `reasoning_output_tokens` is a subset of
`output_tokens` — do not double-count reasoning into pricing.

Crucially, the same rollout file also carries
`payload.rate_limits{primary{used_percent, window_minutes≈300,
resets_at}, secondary{used_percent, window_minutes≈10080, resets_at},
credits{...}, plan_type}`. This means **quota is written to disk by Codex
itself** — remaining budget for both the 5-hour and 7-day windows is
available **fully offline**, from the newest rollout file, with no network
call needed. This is the strongest offline-quota story of any adapter in
this project. A live alternative also exists (RE
`chatgpt.com/backend-api/codex/usage`, or the officially-documented
app-server RPC `account/rateLimits/read`), but is not required for the
core feature.

## Decision

**Full adapter.** Parse rollout JSONL, emit `token_count` deltas as
`UsageEvent`s (fixing up the cached/reasoning subset relationships per
above), and build a `QuotaSnapshot` for both the "5h" and "7d" windows
directly from the newest rollout's `rate_limits` block. Policy:
`Unit.PERCENT`, `CycleKind.ROLLING`, 5h primary window,
`source_of_truth="provider_pct"` — this is the cleanest, most authoritative
offline quota source we have.

## Consequences

**What we get:** a fully offline, provider-reported runway with no RE
endpoint dependency for the core feature — arguably the easiest "full
adapter" win in the whole project, matching the plan's assessment that
"Codex is the simplest offline win".

**Risks:**
- Schema drift: the delta-emission logic depends on `total_token_usage`
  staying cumulative; a future Codex version could change this silently,
  producing negative or nonsensical deltas — the adapter must guard
  against negative deltas and skip them.
- Duplicate rows with unchanged totals must be filtered, or repeated
  zero-token events will pollute session counts.
- If we later add the RE usage endpoint as a supplement, it is
  unversioned and could change without notice.
- `window_minutes` values (~300, ~10080) are approximate/observed, not
  documented constants — treat them as defaults, not guarantees.

## Alternatives considered

- **ccusage/codex** and **cc-statistics** — both parse the same rollout
  JSONL; we implement our own stdlib parser to keep the zero-dependency
  constraint and to feed the shared runway engine.
- **codex-check** — reads auth + limits with `--json` output; useful as a
  cross-check reference, listed in `docs/landscape.md`.
- **OpenTokenMonitor**, **tokscale**, **658jjh** — broader multi-tool
  trackers covering Codex among others.

## Open questions

- Should the adapter surface `credits{...}` (present in `rate_limits`) as
  a secondary budget view alongside the percent windows?
- Is the officially-documented `account/rateLimits/read` RPC worth using
  as an online cross-check instead of the RE HTTP endpoint?
