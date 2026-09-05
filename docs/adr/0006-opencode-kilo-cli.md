# ADR-0006: OpenCode / Kilo CLI adapter

- **Status:** Proposed
- **Date:** 2026-09-05

## Context

OpenCode and Kilo CLI (a fork/relative sharing schema shape) persist to
`~/.local/share/opencode/opencode.db` and `~/.local/share/kilo/kilo.db`
respectively — SQLite databases. The relevant data lives in the
`session_message` table's `data` column, a JSON blob per row shaped as
`{model, cost, tokens{input, output, reasoning, cache{read, write}}}`.
There is no separate quota/budget table in either database.

Both tools are **bring-your-own-key** by default, with an optional "Zen"
plan; neither documents nor enforces a fixed, discoverable local budget
concept in the local database. No official or reverse-engineered
remaining-quota source has been identified for either tool at this time —
budget data, if it exists at all, is server-side and not observable from
the client's local files.

## Decision

**Usage-only.** Read `session_message.data` JSON, parse the embedded
`tokens{...}` (with `cache.read`/`cache.write` and `reasoning` as
distinguished fields) and `cost` for per-session `UsageEvent`s. Estimate
USD from `cost` when present, falling back to the LiteLLM price snapshot
by `model` otherwise. Do not attempt a runway — no local budget concept
exists to compute one against. `default_policy()` should return
`Unit.USD`, `CycleKind.NONE`, `allowance=None`, matching the "no intrinsic
budget" convention used across BYO-key tools in this project.

## Consequences

**What we get:** cost and token attribution for two closely related tools
via one parsing path, useful for the cross-tool cost roll-up and the
local-vs-cloud savings estimator when local models are used through
either CLI.

**Risks:**
- Schema drift: the `data` JSON blob is undocumented and could change
  shape between OpenCode/Kilo releases without notice; field-alias lists
  and skip-on-parse-failure are required, per the project's adapter
  conventions.
- Kilo's schema is assumed, not confirmed, to match OpenCode's exactly —
  divergence would require splitting this into two adapters later.
- If a "Zen" plan does expose a discoverable budget in a future release,
  this ADR's "usage-only" tier would need revisiting toward "full
  adapter".

## Alternatives considered

- **tokscale** — Rust, already covers both OpenCode and Kilo with
  field-alias handling; a useful reference for schema drift resilience.
- **agent-opencode** — a dedicated `opencode.db` reader; narrower scope
  than tokscale but a direct prior-art match.
- **openusage** — reads OpenCode plan caps from local files; worth
  revisiting if it demonstrates a real local budget signal we missed.

## Open questions

- Does the "Zen" plan ever write a discoverable allowance/limit locally,
  and would that justify promoting this to a full adapter?
- Is Kilo's `session_message.data` shape actually identical to OpenCode's,
  or does it diverge enough to warrant a separate adapter module?
