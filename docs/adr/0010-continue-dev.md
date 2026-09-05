# ADR-0010: Continue.dev adapter

- **Status:** Proposed
- **Date:** 2026-09-05

## Context

Continue.dev stores session history as `~/.continue/sessions/<uuid>.json`,
one JSON file per session, containing a session-level `usage` field. This
is explicitly noted as **instable**: field presence and shape have already
been observed to vary between Continue versions, and there is no
documented schema contract from the project. Aggregation is per-session
only — no finer per-turn breakdown is reliably available.

Continue is bring-your-own-key/model; there is no vendor-side budget
concept and no official or reverse-engineered remaining-quota source.

## Decision

**Usage-only, low confidence.** Read `sessions/*.json`, extract the
session-level `usage` object defensively (alias lists, skip files that
don't parse or lack the field), and emit one coarse `UsageEvent` per
session rather than attempting per-turn granularity the format doesn't
reliably provide. No runway: `Unit.USD`, `CycleKind.NONE`,
`allowance=None`. Confidence in the resulting numbers should be
communicated as lower than the other usage-only adapters, given the
field's documented instability.

## Consequences

**What we get:** best-effort cost/token visibility for Continue.dev users
at session granularity, feeding the cross-tool cost roll-up even if
imprecisely.

**Risks:**
- The `usage` field's instability means this adapter is likely to need
  more frequent maintenance than others, and may silently return zero
  events on a Continue version where the field's shape changed
  incompatibly — tests should assert graceful degradation, not just
  the happy path.
- Session-level (not turn-level) granularity means no burn-rate detail
  within a session, only aggregate.
- No local or online budget signal exists at all, so this can never be
  promoted past usage-only without Continue itself exposing one.

## Alternatives considered

- **658jjh/claude-usage-tracker** — includes Continue among its broad,
  admittedly heuristic coverage; comparable confidence level to this
  ADR's own assessment.
- No narrower, actively maintained Continue-specific tracker was found
  during research; this adapter is largely first-of-its-kind for the
  local-runway niche.

## Open questions

- Does the `usage` field's shape correlate with a specific Continue
  version range we could detect and branch on, rather than a flat
  alias-list?
- Would per-turn usage ever become available, and is it worth tracking
  Continue's changelog for that signal?
