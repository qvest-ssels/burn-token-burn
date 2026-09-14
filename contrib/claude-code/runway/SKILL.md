---
name: runway
description: Check how much token budget is left before spending a lot of it. Use before dispatching parallel sub-agents, starting a large refactor, or switching to a frontier model, and whenever the user asks what quota or runway remains.
argument-hint: "[tool]"
allowed-tools: Bash(token-finops:*)
---

# Runway check before you spend

Current runway across every assistant that leaves telemetry on this machine:

!`token-finops status --format plain`

This Claude Code session's own window:

!`token-finops report --tool claude_code --compact`

If either command printed nothing, an error, or `no data`, say so plainly and stop — do not
guess a number. Install/diagnosis lives in `contrib/claude-code/README.md` of
`burn-token-burn`; the fallback is `uv run token-finops report` from a checkout.

## How to read it

`status` prints one segment per tool: short code, used fraction, runway, and a status glyph
(`!` = WARN, `!!` = CRITICAL, `X` = EXHAUSTED). With more than one tool it appends
`binds: <tool>` — the tool that runs out **first**. That is the only number that constrains
the plan; the others are slack.

Runway under `1d` renders in hours (`2h`), so `CC 59% 2h` means: Claude Code is 59% through
its window with about 2.5 hours of headroom left at the current burn rate.

## What to do with it

Decide *before* dispatching, not after:

- **OK, runway comfortably past the reset** — proceed as planned.
- **WARN (`!`), or runway shorter than the work ahead** — shrink the fan-out (fewer
  sub-agents, run them sequentially) or right-size the model: menial work (markdown polish,
  fixtures, boilerplate) goes to a cheap model, only architecture and normalisation logic
  need the frontier one.
- **CRITICAL/EXHAUSTED (`!!`/`X`)** — do not fan out. Tell the user the number and the
  reset time, and offer the cheap-model or do-it-sequentially path instead.

State the number you acted on in one short line (e.g. "runway 2.5 h on the 5 h window —
running these three reviews sequentially on Haiku instead of in parallel on Opus") so the
user can overrule you. Never silently downgrade a model the user chose.

## Digging deeper

- `token-finops report` — full per-tool table with the usage summary.
- `token-finops report --json` — machine-readable; `binding: true` marks the constraining tool.
- `token-finops self-audit` — what *this* Claude Code session has cost so far, sub-agents
  broken out by model. Use it when the user asks "what did that cost?" rather than
  "what is left?".
- `token-finops report --watch 30 --compact` — live pane for a long fan-out.

An argument (`$1`) restricts the check to one tool: run
`token-finops report --tool $1 --compact` instead of the Claude-Code-only line above.
Valid ids: `aider`, `claude_code`, `cline`, `codex`, `continue`, `copilot`, `gemini_cli`,
`hermes`, `opencode`.
