# ADR-0008: Cursor adapter

- **Status:** Accepted (2026-09-05, reference-only as proposed)
- **Date:** 2026-09-05

## Context

Cursor stores its local state in `state.vscdb`, a SQLite database, in a
key-value table `cursorDiskKV`. A `tokenCount` field exists in this store,
but **Cursor's own staff have stated it is unreliable** — it does not
trustworthily reflect actual billed usage. A separate, authoritative
source exists only online: Cursor's dashboard/usage API
(`cursor.com/api/usage`), which is reverse-engineered (unofficial, no
public docs) and requires an authenticated **browser session cookie** to
call — there is no local token or key that grants access. A dashboard CSV
export is also available as a manual, non-automatable fallback.

The budget unit is dollar-credits per month, billed and tracked entirely
server-side; there is no reliable local representation of either usage or
remaining budget.

## Decision

**Reference-only.** Do not implement a Cursor adapter that reads local
`state.vscdb`, since the one local field that could seed a runway
(`tokenCount`) is explicitly disclaimed as unreliable by the vendor's own
staff, and the only reliable source requires a browser-cookie-authenticated
RE endpoint that this project's read-only, credential-free adapter model
is not designed to support. Instead, point users to existing tools that
already do this work, accepting the cookie-auth requirement, in
`docs/landscape.md`.

## Consequences

**What we get:** we avoid shipping an adapter that silently produces
wrong runway numbers from data Cursor's own engineers say not to trust,
protecting this project's credibility on its core "runway" claim.

**Risks:**
- Users who want Cursor coverage must run a separate tool and manage its
  cookie-based auth themselves; there is a coverage gap in the
  cross-tool roll-up (Cursor cannot participate in the "binding
  constraint / minimum runway" computation described in the project
  plan).
- If Cursor later exposes a documented, reliable local usage field or a
  key-based (non-cookie) API, this decision should be revisited toward a
  usage-only or full adapter.

## Alternatives considered

- **cursor-stats** ([Dwtexe/cursor-stats](https://github.com/Dwtexe/cursor-stats),
  GPL-3.0) — already implements the dashboard-API-with-cookie approach;
  the primary recommendation for Cursor users.
- **tokscale** — covers Cursor via CSV export as a lower-friction, if
  manual, alternative that avoids cookie auth entirely.
- **cc-statistics** — includes Cursor in a combined dashboard, same
  dashboard-API dependency.

## Open questions

- Would a manual CSV-import mode (matching tokscale's approach) be worth
  adding later as a middle ground between "reference-only" and a live
  cookie-authenticated adapter?
- Should this project contribute a fix or a documented caveat upstream if
  Cursor ever clarifies the intended reliability of `tokenCount`?
