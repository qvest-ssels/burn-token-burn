"""Drift guard between cli.py's argparse tree and contrib/completions/.

The shell completion scripts are static, hand-maintained files (no argcomplete, no
generator, no build step -- see contrib/completions/*). That is the right trade-off for
three small files, but it means a new or renamed subcommand can silently stop being
completable. So instead of duplicating the list here, this introspects the *real*
argparse subparsers at import time and asserts every name that actually exists shows up
in each of the three scripts, in the place that shell would actually read it from.

Deliberately not asserted: that the scripts contain *only* real subcommands. A script
may legitimately run ahead of `main` (a subcommand landing in a concurrent PR), and
offering one extra completion candidate is harmless; a *missing* one is the drift we
care about. Same containment style as test_cli_smoke_workflow.py -- no shell parser,
just the lines each shell keys off.
"""
from __future__ import annotations

import argparse
import os
import re

import pytest

from token_finops_cli.adapters import all_adapters
from token_finops_cli.cli import build_parser

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMPLETIONS_DIR = os.path.join(_ROOT, "contrib", "completions")
BASH = os.path.join(COMPLETIONS_DIR, "token-finops.bash")
ZSH = os.path.join(COMPLETIONS_DIR, "token-finops.zsh")
FISH = os.path.join(COMPLETIONS_DIR, "token-finops.fish")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def subcommands() -> list[str]:
    """Every subcommand argparse actually knows about, straight from build_parser()."""
    all_adapters()  # populate the adapter registry the way main() does
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return sorted(action.choices)
    raise AssertionError("cli.build_parser() has no subparsers any more")


SUBCOMMANDS = subcommands()


def test_there_are_subcommands_to_check():
    # guards against the introspection silently returning [] and the tests below passing
    assert len(SUBCOMMANDS) >= 5, SUBCOMMANDS
    assert "report" in SUBCOMMANDS


@pytest.mark.parametrize("path", [BASH, ZSH, FISH])
def test_completion_scripts_exist(path):
    assert os.path.isfile(path), f"{os.path.basename(path)} is missing from contrib/completions/"


def _case_labels(text: str, opener: str) -> set[str]:
    """The branch labels of the `case` block introduced by *opener* ("foo|bar)" -> {foo, bar}).

    Uses the *last* occurrence of *opener*: the scripts nest a small `case` on the same
    variable inside a flag-value branch, and the per-subcommand dispatch is the outer,
    later one.
    """
    assert opener in text, f"expected a `{opener}` block in this completion script"
    body = re.split(r"\n\s*esac\b", text.rsplit(opener, 1)[1], maxsplit=1)[0]
    labels: set[str] = set()
    for line in body.splitlines():
        match = re.match(r"\s*([A-Za-z0-9|_-]+)\)", line)
        if match:
            labels.update(match.group(1).split("|"))
    return labels


@pytest.mark.parametrize("name", SUBCOMMANDS)
def test_bash_completes_subcommand(name):
    text = _read(BASH)
    # the word list `complete -F` offers when no subcommand has been typed yet
    start = text.index('_token_finops_commands="') + len('_token_finops_commands="')
    commands = text[start:text.index('"', start)].split()
    assert name in commands, f"`{name}` missing from _token_finops_commands in token-finops.bash"
    # ... and each one needs a branch in the per-subcommand flag `case` statement
    assert name in _case_labels(text, 'case "$cmd" in'), \
        f"`{name}` has no flag branch in token-finops.bash's `case \"$cmd\"` statement"


@pytest.mark.parametrize("name", SUBCOMMANDS)
def test_zsh_completes_subcommand(name):
    text = _read(ZSH)
    assert text.startswith("#compdef token-finops"), "zsh completion needs a #compdef header"
    # _describe reads the `commands=( 'name:description' ... )` array
    assert f"'{name}:" in text, f"`{name}` missing from the commands array in token-finops.zsh"
    # ... and each one needs an arm in the `case $words[1]` dispatch
    assert name in _case_labels(text, "case $words[1] in"), \
        f"`{name}` has no `case $words[1]` arm in token-finops.zsh"


@pytest.mark.parametrize("name", SUBCOMMANDS)
def test_fish_completes_subcommand(name):
    text = _read(FISH)
    assert f"-a {name} -d " in text, \
        f"`{name}` missing as a `complete -c token-finops ... -a {name}` line in token-finops.fish"
    # ... and, unless it genuinely takes no flags, a `__fish_seen_subcommand_from` block
    flagless = {"collect-statusline", "adapters"}
    if name not in flagless:
        assert re.search(rf"__fish_seen_subcommand_from [\w\s-]*\b{re.escape(name)}\b", text), \
            f"`{name}` has no per-subcommand flag completions in token-finops.fish"


@pytest.mark.parametrize("path", [BASH, ZSH, FISH])
def test_completion_scripts_have_no_third_party_dependency(path):
    """These are static by design -- nothing may shell out to argcomplete/shtab at runtime."""
    code = "\n".join(ln for ln in _read(path).lower().splitlines() if not ln.lstrip().startswith("#"))
    for forbidden in ("argcomplete", "shtab", "token-finops --help", "python"):
        assert forbidden not in code, f"{os.path.basename(path)} must stay static ({forbidden})"


@pytest.mark.parametrize("path", [BASH, ZSH, FISH])
def test_install_doc_documents_every_script(path):
    doc = _read(os.path.join(_ROOT, "docs", "INSTALL.md"))
    assert os.path.basename(path) in doc, \
        f"docs/INSTALL.md must say how to install {os.path.basename(path)}"


def test_tool_choices_match_the_adapter_registry():
    """--tool's choices come from the adapter registry; the scripts hardcode that list."""
    from token_finops_cli.adapters.base import registry

    all_adapters()
    for path in (BASH, ZSH, FISH):
        text = _read(path)
        for tool in sorted(registry):
            assert tool in text, f"adapter `{tool}` missing from --tool completions in {os.path.basename(path)}"
