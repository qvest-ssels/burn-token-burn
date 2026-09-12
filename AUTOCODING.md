# AUTOCODING.md — which CLI/model wrote this repo, and how we split the work

`AGENTS.md` is the rulebook for a coding agent working in this repository. This file is
the practice log: which tool actually wrote each part, on what model, and why — in the
same spirit as the talk this project grew out of ("Warum zu viele Tokens nicht die
Lösung sind"). If you're wondering whether a human wrote a given line, the honest answer
for almost all of it is no; this file says which agent did, and on what budget.

## The two seats

**Cloud session (Cowork, this repo's primary author).** An Anthropic Cowork session
running Claude — model has moved between `claude-fable-5-1` and `claude-sonnet-5` across
this project as the maintainer switched with `/model`. This seat has no local shell on
the maintainer's Mac; it reaches the Mac's files only through the remote-devices bridge
(stage → edit in the sandbox → commit back), and reaches GitHub only by producing a
git bundle for the maintainer's own `git push` — it cannot authenticate to GitHub itself.

**Local Claude Code CLI (the maintainer's Mac).** Ordinary `claude` runs in
`~/workspace/burn-token-burn`, on the maintainer's own Claude Code subscription. Used for
work that (a) doesn't need the cloud session's device-bridge/orchestration overhead, and
(b) should be paid for out of the Code CLI's own plan rather than the cloud session's
token budget — see "Why split spend across two seats" below.

Both seats read `AGENTS.md`/`CLAUDE.md` for the repo's ground rules; neither commits
directly to `main` when working a `claude-tasks.md` item — that's the branch-per-task,
PR-with-self-audit-table workflow described there.

## Model assignment (from `AGENTS.md` rule 8, "right-size the model")

| Work | Model | Why |
|---|---|---|
| Architecture: runway engine, normalisation rules, adapter dedup logic, the `burn` maxing-multiplier design | Opus / Fable (cloud session) | Judgement-heavy; wrong here is expensive to unwind later. |
| Adapter boilerplate, one-off research (landscape survey, install-command lookups), CI plumbing | Sonnet (cloud sub-agent, `Agent` tool) | Mechanical once the shape is decided; still needs to read real docs/source. |
| Test suites against synthetic fixtures, robustness/fuzz cases | Fable or Sonnet sub-agent, whichever isn't the architecture bottleneck that day | Wide but shallow — good sub-agent fan-out shape. |
| Markdown polish, doc drafting from an already-decided outline | **Haiku sub-agent** (cloud, via `Agent` tool with a Haiku model override), moving to **local Claude Code CLI runs** | Cheapest useful model for prose that doesn't require new judgement calls; see below for the local-CLI move. |

## Why split spend across two seats

The cloud session's tokens are billed against this Cowork session's own budget
regardless of which model does the work — a Haiku sub-agent still costs cloud-session
tokens, just fewer of them. Fanning doc-writing tasks out to the maintainer's **local**
Claude Code CLI instead spends his own Code CLI plan (currently a discounted-rate
window) rather than the cloud session's budget, for exactly the kind of work (drafting
docs from a settled outline) that doesn't need the cloud session's orchestration or
device-bridge access.

Practically, that means: a documentation task with a clear, already-agreed-on outline
(e.g. "write the OpenCode/Kilo section of `docs/INSTALL.md` Tier 2, following the Tier-1
sections' structure and sourcing rules") is dispatched as a `claude -p "<prompt>" --model
<haiku alias>` run via `device_bash` on the maintainer's Mac, writing directly into the
connected `burn-token-burn` checkout, rather than as an `Agent` call inside the cloud
session.

## Token accounting for local-CLI fan-out

Every local run writes its own transcript under `~/.claude/projects/**` like any other
Claude Code session, which means `token-finops self-audit` (this very repo's own tool)
can be pointed at that session id afterward to report exactly what it cost — real
telemetry, not an estimate, dogfooding the tool on its own construction. The practice:

1. Dispatch the doc-writing prompt via `device_bash` running `claude -p "…" --model
   <haiku alias>` in the target directory (a single-shot run, not an interactive
   session).
2. After it returns, run `token-finops self-audit --session latest` (or the printed
   session id) via `device_bash` in the same checkout, to get calls / tokens /
   API-equivalent for that specific run.
3. Log the outcome under "Local-CLI doc runs" below: task, session id, tokens,
   API-equivalent, and which file(s) it produced.

This is new practice as of 2026-09-12 — the log below starts empty and grows as runs
happen, the same way `docs/PLAN.md`'s dogfooding section does for the cloud seat.

## Local-CLI doc runs (log)

| Date | Task | Session id | Tokens | API-eq $ | Files |
|---|---|---|---|---|---|
| — | *(none yet — first runs land here after the maintainer approves the fan-out plan)* | | | | |

## Cloud-session dogfooding (for comparison)

See `docs/PLAN.md`'s status line and `docs/BURN.md`'s worked example for the cloud
seat's own self-audit numbers (calls, tokens, API-equivalent, maxing multiplier against
the maintainer's plan). The point of this file existing alongside those is to make the
*routing* decision — which seat did a given piece of work, and why — as visible as the
cost numbers themselves.
