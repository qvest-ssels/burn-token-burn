---
description: Check the remaining token-budget runway before a large task or a parallel fan-out.
argument-hint: "[tool]"
---

Run these two commands and report what they say:

```bash
token-finops status --format plain
token-finops report --tool codex --compact
```

`status` prints one segment per tool — short code, used fraction, runway, status glyph (`!` =
WARN, `!!` = CRITICAL, `X` = EXHAUSTED) — and appends `binds: <tool>` for the tool that runs
out first. That one is the constraint; the rest is slack. A runway under a day renders in
hours, so `CX 59% 2h` means 59% of the window used with roughly 2.5 hours of headroom at the
current burn rate.

Then decide, before starting the work rather than after:

- OK and runway past the reset — proceed.
- WARN, or runway shorter than the work ahead — narrow the scope, or move the menial parts
  (boilerplate, fixtures, docs polish) to a cheaper model.
- CRITICAL or EXHAUSTED — stop and tell me the number and the reset time instead of starting.

If the commands are not found or print no data, say so — do not guess a number.

With an argument, check that tool instead: `token-finops report --tool $1 --compact`. Valid
ids: `aider`, `claude_code`, `cline`, `codex`, `continue`, `copilot`, `gemini_cli`, `hermes`,
`opencode`. Full detail: `token-finops report`, or `token-finops report --json` where
`binding: true` marks the constraining tool.
