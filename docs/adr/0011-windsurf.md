# ADR-0011: Windsurf adapter

- **Status:** Accepted (2026-09-05, reference-only as proposed)
- **Date:** 2026-09-05

## Context

Windsurf's local state contains **no token or usage fields at all**.
Credits are tracked and enforced entirely server-side; there is no local
database, JSON file, or log that reflects consumption, cost, or remaining
budget. No official or reverse-engineered local telemetry source was
identified during research — this is not a matter of an unreliable field
(as with Cursor) but of the data's outright absence from disk.

## Decision

**Not feasible locally; reference-only.** No adapter will be implemented
for Windsurf, because there is nothing on disk to read — the entire
"read the tool's local telemetry" premise this project is built on does
not apply. `docs/landscape.md` should note this plainly (as it already
does) so users understand why Windsurf has no entry among the
tool-specific tracker sections, rather than assuming an oversight.

## Consequences

**What we get:** an honest gap rather than a fabricated or speculative
adapter; this keeps the project's "we only ship what's locally verifiable"
principle intact.

**Risks:**
- Windsurf users get zero coverage in the cross-tool roll-up; if Windsurf
  usage is significant for a given developer, their "binding constraint"
  runway will silently omit it rather than flag it as unknown — the CLI
  and docs must make this omission explicit rather than implying
  completeness.
- If Windsurf ever ships local telemetry (or a documented API) in a
  future release, this decision should be revisited.

## Alternatives considered

- No existing open-source tool was found that reads local Windsurf
  telemetry, for the same reason we cannot: there isn't any. No
  alternative to recommend beyond Windsurf's own in-product usage view.

## Open questions

- Should token-finops's cross-tool roll-up display an explicit "Windsurf:
  not tracked" placeholder row, to avoid users mistaking silence for zero
  usage?
- Is it worth periodically re-checking Windsurf's local storage in case a
  future release adds any telemetry file?
