# ADR-0007: Cline / Roo / Kilo (VS Code extensions) adapter

- **Status:** Proposed
- **Date:** 2026-09-05

## Context

Cline, Roo, and the VS Code variant of Kilo each store their per-task
history under VS Code's extension global storage:
`…/globalStorage/<extension-id>/tasks/<task-id>/ui_messages.json`. Inside
this JSON array, entries of type `api_req_started` carry a nested,
stringified JSON payload with `{tokensIn, tokensOut, cacheReads,
cacheWrites, cost}`. This is a UI-message log, not a purpose-built
telemetry store — usage data is embedded incidentally inside a message
meant for rendering the chat UI.

All three are **bring-your-own-key** tools with no vendor-side budget
concept exposed locally; cost is whatever the underlying model provider
charges, already computed and embedded per request as `cost`. No official
or reverse-engineered remaining-quota source exists for any of the three.

## Decision

**Usage-only.** Parse `ui_messages.json` for each task directory, extract
and JSON-decode the `api_req_started` payloads, and emit one
`UsageEvent` per request using `tokensIn/tokensOut/cacheReads/cacheWrites`
and the pre-computed `cost` field directly (no need to re-price via
LiteLLM when `cost` is present and non-null). No runway: `Unit.USD`,
`CycleKind.NONE`, `allowance=None`.

## Consequences

**What we get:** usage/cost visibility for three popular VS Code coding
agents via one shared parser, since their `ui_messages.json` shape is
effectively identical.

**Risks:**
- The `api_req_started` payload is an internal UI message format, not a
  documented telemetry schema — the most drift-prone source in this
  project. Field presence/naming must be defensively aliased, and this
  adapter should be the first to break on an extension update.
- Locating `globalStorage/<extension-id>/` paths differs across VS Code,
  VS Code Insiders, VSCodium, and Cursor-as-host, requiring a search
  across multiple known extension IDs and possible install roots.
- Multiple forks (Cline, Roo, Kilo-VSCode) sharing this format is an
  assumption to verify per extension; if one fork's ID or field names
  diverge, it needs its own alias branch, not a silent skip.
- Reading VS Code's global storage while the editor is running risks file
  lock contention; read-only, non-blocking access is required.

## Alternatives considered

- **tokscale** — already parses this exact `ui_messages.json` shape
  across Cline/Roo; the primary reference for extension-ID discovery and
  field aliases.
- No other narrower tool specifically targets this format; broader
  trackers (658jjh) attempt it heuristically.

## Open questions

- Should each fork (Cline/Roo/Kilo-VSCode) get its own adapter module for
  isolation against independent schema drift, or is one shared module
  with an extension-ID list acceptable long-term?
- Is there a reliable way to enumerate all installed extension IDs rather
  than hardcoding a known list that will go stale?
