# Codex CLI `/runway` custom prompt

Same idea as `contrib/claude-code/` (`docs/INTEGRATIONS.md` §3), in the shape Codex CLI
actually supports: a **custom prompt** — a single markdown file with optional YAML
frontmatter (`description`, `argument-hint`), dropped in `~/.codex/prompts/`, invoked as
`/prompts:runway`. Arguments are `$1`…`$9` positionally.

Codex is the best-behaved data source we have: it writes `rate_limits` to disk itself
(ADR-0003), so the answer is available offline and instantly.

## Install

```bash
mkdir -p ~/.codex/prompts
cp contrib/codex/prompts/runway.md ~/.codex/prompts/
```

Then `/prompts:runway` in a Codex session (`/prompts:runway copilot` to narrow to one tool).
Note the `prompts:` prefix — unlike Claude Code, the file name is not a bare slash command.

`token-finops` must be on `PATH`; see `docs/INSTALL.md`.

## Caveat, honestly

Custom prompts are documented but marked **deprecated in favour of a newer "skills"
mechanism**. We ship the prompt form because it is the one that is currently documented and
verifiable end to end; the successor's file layout is not stable enough to commit a file
against yet. When it is, this directory gets a `skills/` sibling and the prompt stays as the
fallback. Per the "say so instead of inventing an API" rule in `docs/INTEGRATIONS.md`, we are
not guessing at it in the meantime.

## Smoke test

Covered by `token-finops-cli/tests/test_contrib_skills.py` alongside the Claude Code skill:
every `token-finops …` command in this prompt is `shlex.split()` and fed to the real argparse
parser, so a non-existent flag fails CI.
