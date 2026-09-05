# ADR-0009: Aider adapter

- **Status:** Proposed
- **Date:** 2026-09-05

## Context

Aider writes a running Markdown chat log at `.aider.chat.history.md`
inside the working directory. Usage information appears only as
human-readable text embedded in that log, in a line of the form
`> Tokens: N sent, M received. Cost: $x`, which must be recovered by
regular expression — there is no structured field. Aider optionally
supports `--analytics-log x.jsonl` for structured, opt-in JSONL analytics,
which is more reliable when present but is not enabled by default and
cannot be assumed to exist.

Aider is bring-your-own-key; there is no vendor-side budget concept and
no official or reverse-engineered remaining-quota source. Because parsing
depends on regex-matching a Markdown log intended for humans, this source
is inherently more fragile than the JSON/SQLite sources used elsewhere in
this project.

## Decision

**Usage-only, low priority.** Implement a regex-based parser for
`.aider.chat.history.md` as the default path, extracting sent/received
token counts and the reported cost per turn, with `--analytics-log` JSONL
preferred and used instead whenever present (structured, less fragile).
No runway: `Unit.USD`, `CycleKind.NONE`, `allowance=None`. This adapter is
explicitly lower priority than the JSONL/SQLite-backed adapters (ADR-0001
through ADR-0006) given its regex dependency on a human-facing log format.

## Consequences

**What we get:** basic cost/token visibility for Aider users without
requiring them to enable analytics logging, plus a stronger path when
they do.

**Risks:**
- Regex-based Markdown parsing is the most drift-prone approach in this
  project: formatting changes (locale-dependent number formatting,
  wording changes, log-line reordering) can silently break extraction with
  no schema to validate against.
- `.aider.chat.history.md` is per-working-directory, not a single global
  store — multi-repo users need this adapter to scan many locations, and
  discovery logic (where do these files live?) is inherently heuristic.
- Cost text embeds whatever currency/precision Aider chose to print;
  parsing must not assume a fixed decimal format.

## Alternatives considered

- **658jjh/claude-usage-tracker** — already attempts Aider heuristically
  among many other tools; acknowledged as heuristic rather than reliable,
  matching our own assessment.
- Encouraging `--analytics-log` adoption is the most durable fix; this
  ADR treats it as the preferred path over the regex log scrape whenever
  available.

## Open questions

- Should the adapter warn users explicitly when it falls back to
  regex-parsing (as opposed to `--analytics-log`), so they understand the
  lower confidence of the resulting numbers?
- Is it worth contributing a small patch upstream to Aider to always emit
  a structured analytics line, reducing our own maintenance burden?
