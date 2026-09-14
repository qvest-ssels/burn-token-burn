"""Smoke test for the agent-native surfaces in `contrib/` (docs/INTEGRATIONS.md §3).

A skill file is prose until an agent runs it, so the failure mode is a command string that
looks fine in review and blows up in someone's session. This test treats every
`token-finops …` string in `contrib/claude-code/` and `contrib/codex/` as executable:

1. it must `shlex.split()` (valid shell, balanced quotes);
2. `argv[0]` must be `token-finops`;
3. the rest must parse against the *real* argparse parser, so a flag the CLI does not have
   (or a `--tool` id that is not registered) fails here instead of in production.

Skipped when `contrib/` is absent — the package ships as a subtree and can be checked out
without the surrounding repo.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from token_finops_cli.adapters import all_adapters
from token_finops_cli.cli import _normalize_argv, build_parser

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRIB = REPO_ROOT / "contrib"

SKILL = CONTRIB / "claude-code" / "runway" / "SKILL.md"
CODEX_PROMPT = CONTRIB / "codex" / "prompts" / "runway.md"

pytestmark = pytest.mark.skipif(not CONTRIB.is_dir(), reason="contrib/ not present in this checkout")

FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)   # fenced block (```bash … ```)
INLINE_RE = re.compile(r"`([^`\n]+)`")                # inline span, incl. ``!`…` `` injections
# Placeholders a skill body may legitimately contain: `$1` positional, `$ARGUMENTS`.
PLACEHOLDER = re.compile(r"\$(?:\d|ARGUMENTS\b|\{[^}]+\})")


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal `key: value` YAML frontmatter reader (stdlib only — no PyYAML dependency)."""
    assert text.startswith("---\n"), "file must open with a YAML frontmatter fence"
    end = text.index("\n---\n", 3)
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        assert ":" in line, f"unparsable frontmatter line: {line!r}"
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip().strip('"').strip("'")
    return meta, text[end + 5:]


def commands_in(path: Path) -> list[str]:
    """Every `token-finops …` line a reader/agent would actually execute.

    Only code — fenced blocks and inline spans, the latter covering ``!`…` `` context
    injection. Prose mentioning the binary by name is not a command and is ignored.
    """
    _, body = split_frontmatter(path.read_text(encoding="utf-8"))
    snippets: list[str] = []
    for block in FENCE_RE.findall(body):
        snippets += block.splitlines()
    snippets += INLINE_RE.findall(FENCE_RE.sub("", body))
    found = [s.strip() for s in snippets if s.strip().split()[:1] == ["token-finops"]]
    assert found, f"no token-finops commands found in {path}"
    return found


def assert_parses(cmd: str) -> None:
    """Valid shell, and every flag/choice is one the installed CLI really has."""
    # `$1` etc. stand in for a user argument; substitute a real tool id so choices validate.
    argv = shlex.split(PLACEHOLDER.sub("claude_code", cmd))
    assert argv[0] == "token-finops", cmd
    all_adapters()  # populate the adapter registry so --tool choices exist
    build_parser().parse_args(_normalize_argv(argv[1:]))


# --------------------------------------------------------------------------- #
# Claude Code skill
# --------------------------------------------------------------------------- #
def test_claude_code_skill_is_a_directory_with_skill_md():
    # Claude Code requires `<skills-dir>/<name>/SKILL.md`; a flat `<name>.md` is not loaded.
    assert SKILL.is_file()
    assert SKILL.name == "SKILL.md"
    assert SKILL.parent.name == "runway", "directory name is the /command name"


def test_claude_code_skill_frontmatter():
    meta, body = split_frontmatter(SKILL.read_text(encoding="utf-8"))
    assert meta["name"] == SKILL.parent.name
    # description is what makes the model invoke it before a fan-out; it is also capped.
    assert 0 < len(meta["description"]) <= 250, len(meta["description"])
    assert "sub-agent" in meta["description"]
    assert meta["allowed-tools"].startswith("Bash(token-finops")
    assert body.strip(), "skill body must not be empty"


def test_claude_code_skill_commands_parse():
    for cmd in commands_in(SKILL):
        assert_parses(cmd)


def test_claude_code_skill_mentions_the_two_contract_commands():
    text = SKILL.read_text(encoding="utf-8")
    assert "token-finops status --format plain" in text
    assert "token-finops report --tool claude_code" in text


# --------------------------------------------------------------------------- #
# Codex custom prompt
# --------------------------------------------------------------------------- #
def test_codex_prompt_is_a_flat_markdown_file():
    # Codex custom prompts are single files in ~/.codex/prompts/, invoked as /prompts:<name>.
    assert CODEX_PROMPT.is_file() and CODEX_PROMPT.suffix == ".md"
    assert CODEX_PROMPT.parent.name == "prompts"


def test_codex_prompt_frontmatter_and_commands():
    meta, body = split_frontmatter(CODEX_PROMPT.read_text(encoding="utf-8"))
    assert meta["description"]
    assert body.strip()
    for cmd in commands_in(CODEX_PROMPT):
        assert_parses(cmd)


# --------------------------------------------------------------------------- #
def test_tool_ids_advertised_in_contrib_are_all_registered():
    """The skills list the valid `--tool` ids inline; keep that list honest as adapters land."""
    registered = {ad.tool for ad in all_adapters()}
    for path in (SKILL, CODEX_PROMPT):
        text = path.read_text(encoding="utf-8")
        listed = set(re.findall(r"`(aider|claude_code|cline|codex|continue|copilot|"
                                r"gemini_cli|hermes|opencode)`", text))
        assert listed, f"{path} should list the valid tool ids"
        assert listed <= registered, f"{path} lists unregistered tools: {listed - registered}"
