# Claude Code `/runway` skill

Agent-native surface from `docs/INTEGRATIONS.md` §3: the status line is passive, `/runway` is
the thing the model can call *mid-task, before it spends*. It shells out to `token-finops` and
tells the agent to check the budget before fanning out sub-agents.

A Claude Code skill is a directory containing `SKILL.md` (YAML frontmatter + markdown body).
A flat `skills/runway.md` file is **not** valid — it must be `runway/SKILL.md`.

## Install

Project scope (commit it, whole team gets `/runway`):

```bash
mkdir -p .claude/skills
cp -r contrib/claude-code/runway .claude/skills/
```

Personal scope (every project, not committed):

```bash
mkdir -p ~/.claude/skills
cp -r contrib/claude-code/runway ~/.claude/skills/
```

The directory name is the command name, so `runway/` gives you `/runway`. Restart Claude Code
(or start a new session) and `/runway` shows up in the `/` menu.

`token-finops` must be on `PATH` — `uv tool install token-finops-cli`, or see
`docs/INSTALL.md`. Without it the skill's commands print nothing and it says so instead of
inventing a number.

## Invocation

Two ways, both intended:

- **You type `/runway`** (optionally `/runway copilot` to narrow to one tool).
- **Claude invokes it itself** when the `description` matches what it is about to do — which
  is the whole point: the check is worth something in the seconds *before* three frontier
  sub-agents get dispatched, and that is exactly when nobody types a command.

If you only ever want the manual form, add `disable-model-invocation: true` to the
frontmatter.

## Notes

- `allowed-tools: Bash(token-finops:*)` pre-approves just this one binary, so the injected
  commands do not raise a permission prompt. Drop the line if you would rather be asked.
- The body runs its commands via `` !`…` `` context injection at skill-load time, so the
  numbers are in context before Claude reasons about them.
- `status` reads the cache in `~/.token-finops/last.json` and only rescans when it is older
  than 5 minutes — see `contrib/refresh/` for a timer that keeps it warm. `report` always
  scans; that is fine for a command you run a handful of times a session.

## Smoke test

`token-finops-cli/tests/test_contrib_skills.py` parses the frontmatter and feeds every
`token-finops …` command in this file through `shlex.split()` and the real argparse parser, so
a flag that does not exist fails the test suite rather than a user's session:

```bash
cd token-finops-cli && uv run pytest -q tests/test_contrib_skills.py
```
