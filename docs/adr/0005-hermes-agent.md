# ADR-0005: Hermes Agent adapter

- **Status:** Accepted (2026-09-05, adapter implemented)
- **Date:** 2026-09-05

## Context

Hermes Agent persists to `${HERMES_HOME:-~/.hermes}/state.db` (SQLite,
WAL mode). The `sessions` table carries `id, source, model, started_at,
ended_at, message_count, api_call_count, input_tokens, output_tokens,
cache_read_tokens, cache_write_tokens, reasoning_tokens,
billing_provider, billing_base_url, billing_mode, estimated_cost_usd,
actual_cost_usd, cost_status, cost_source, parent_session_id, title`.
Newer builds add `session_model_usage` (session × model × provider, same
columns), preferred when present (check `sqlite_master`, fall back to
`sessions`). A legacy per-session JSONL also exists but is optional.
Granularity is session-level, timestamped by `ended_at` or `started_at`.

Hermes is a **bring-your-own-provider** agent, so there is no single
budget concept. `billing_mode`/`billing_provider`/`billing_base_url`
decide what "budget" means per session: localhost or a provider in
`(ollama, lmstudio, vllm, local)` means `is_local_model=True`,
`usd_estimate=None` — tokens only. `billing_provider == "openrouter"`
means real dollars (`native_cost`, `native_unit=Unit.USD`), and
OpenRouter's key API (`GET openrouter.ai/api/v1/key` →
`limit_remaining, usage_daily/weekly/monthly`) is an **officially
documented, online** quota source. No offline budget exists for local
models, nor for a Codex-subscription passthrough (usage is "included").

## Decision

**Usage-only, with provider passthrough where the underlying provider has
its own enforced budget.** Emit `UsageEvent`s for every session/row with
correct `is_local_model` and `native_cost` handling as above. Do **not**
claim a Hermes-native runway — there is no Hermes-level budget concept to
compute a runway against. Where `billing_provider == "openrouter"`, treat
OpenRouter's key-API response as an optional online `QuotaSnapshot`
source (`Unit.USD`, `CycleKind.SLIDING_FROM_FIRST_USE` at 30 days as a
practical default, since OpenRouter itself doesn't publish a fixed
cycle), explicitly documented as `source_of_truth="local_sum"` when
offline and provider-sourced when the key API is queried.

## Consequences

**What we get:** correct cost/token attribution across a heterogeneous set
of backends (local models, OpenRouter, Codex-subscription passthrough)
without inventing a fictitious "Hermes budget" that doesn't exist.

**Robustness:** The adapter degrades gracefully when the newer `session_model_usage`
table is absent, falling back to the `sessions` table; when the `sessions` table
exists without optional columns (e.g. reasoning tokens, cache columns), they
default to zero. Corrupt SQLite files are skipped silently, leaving the adapter
non-functional for that store but not crashing the overall scan.

**Risks:**
- `billing_mode` values are not a fixed enum across versions; alias/
  fallback logic is required, and an unrecognized mode should default to
  "unknown cost" rather than a wrong dollar estimate.
- `session_model_usage` vs `sessions` table selection could silently
  double-count if both are read for the same session.
- OpenRouter's key API needs an API key with read scope; if absent, the
  adapter must degrade to local-sum only, not error.
- Local-model sessions feed the local-vs-cloud savings estimator
  (ADR-0012) — bugs here propagate into that comparison.

## Alternatives considered

- **ccusage/hermes** — experimental Hermes source; useful field mapping.
- **hermes-token-cost** — plugin reading `state.db` read-only, closest
  prior art.
- **hermes-dashboard** — dashboard over `state.db` plus a proxy DB,
  Anthropic pricing only (narrower than our multi-provider handling).
- **tokscale** — broader multi-tool coverage including Hermes.

## Open questions

- Should we surface a per-provider runway (e.g. OpenRouter dollars) as a
  first-class row in the cross-tool roll-up, or only as a detail view
  given it's provider-, not agent-, level budget?
- Is a 30-day sliding window the right default cycle for OpenRouter usage
  absent a documented cycle, or should we only report `used_units`
  without a cycle at all?
