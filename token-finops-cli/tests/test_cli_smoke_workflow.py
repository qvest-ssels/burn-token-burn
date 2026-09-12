"""Consistency check between docs/INSTALL.md and .github/workflows/cli-smoke.yml.

This does NOT run the smoke test itself (that needs GitHub-hosted runners, real
package registries, and Homebrew — see T-18 in claude-tasks.md and the workflow's own
header comment). It runs locally and fast, and exists so a doc edit that silently
drifts from what CI actually installs (or vice versa) fails here instead of being
discovered when someone follows a stale command. Plain string containment, not a YAML
parse — this repo and its test suite stay stdlib-only; the workflow file is small and
line-oriented enough that this catches the drift we actually care about.
"""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOW = os.path.join(_ROOT, ".github", "workflows", "cli-smoke.yml")
INSTALL_DOC = os.path.join(_ROOT, "docs", "INSTALL.md")

# tool -> the exact strings both files must agree on
TIER1 = {
    "claude-code": {"npm_package": "@anthropic-ai/claude-code", "brew": "--cask claude-code", "bin": "claude"},
    "copilot-cli": {"npm_package": "@github/copilot", "brew": None, "bin": "copilot"},
    "codex-cli": {"npm_package": "@openai/codex", "brew": "--cask codex", "bin": "codex"},
    "gemini-cli": {"npm_package": "@google/gemini-cli", "brew": "gemini-cli", "bin": "gemini"},
}
VSCODE_EXTENSIONS = {
    "cline": "saoudrizwan.claude-dev",
    "roo-code": "RooVeterinaryInc.roo-cline",
    "kilo-code": "kilocode.Kilo-Code",
}


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_workflow_and_install_doc_files_exist():
    assert os.path.isfile(WORKFLOW), "cli-smoke.yml is missing"
    assert os.path.isfile(INSTALL_DOC), "docs/INSTALL.md is missing"


def test_workflow_covers_every_tier1_npm_tool():
    wf = _read(WORKFLOW)
    for tool, info in TIER1.items():
        assert f"tool: {tool}" in wf, f"{tool} missing from cli-smoke.yml npm-cli matrix"
        assert info["npm_package"] in wf, f"{info['npm_package']} missing from cli-smoke.yml"
        assert info["bin"] in wf, f"{info['bin']} --version step missing from cli-smoke.yml"
    assert "macos-latest" in wf and "ubuntu-latest" in wf, "npm-cli matrix must cover both OSes"


def test_workflow_covers_every_tier1_brew_formula():
    wf = _read(WORKFLOW)
    for tool, info in TIER1.items():
        if info["brew"] is None:
            continue  # e.g. copilot-cli: no Homebrew formula exists, documented as npm-only
        assert info["brew"] in wf, f"brew formula/cask for {tool} missing from cli-smoke.yml"


def test_workflow_covers_vscode_extensions():
    wf = _read(WORKFLOW)
    for tool, ext_id in VSCODE_EXTENSIONS.items():
        assert ext_id in wf, f"{tool} extension id {ext_id} missing from cli-smoke.yml"
    assert "--cask visual-studio-code" in wf


def test_install_doc_matches_workflow_commands():
    """Every command the workflow runs must also be the one INSTALL.md tells a human to run."""
    doc = _read(INSTALL_DOC)
    for tool, info in TIER1.items():
        assert info["npm_package"] in doc, f"{info['npm_package']} missing from INSTALL.md ({tool})"
        if info["brew"] is not None:
            assert info["brew"] in doc, f"brew command for {tool} missing from INSTALL.md"
    for ext_id in VSCODE_EXTENSIONS.values():
        assert ext_id in doc, f"{ext_id} missing from INSTALL.md"


def test_install_doc_flags_copilot_has_no_brew_formula():
    # Regression guard: copilot-cli must stay documented as npm-only until GitHub ships
    # a Homebrew formula. If this ever needs to flip, cli-smoke.yml's brew-cli matrix
    # (and this test's TIER1 table) must be updated in the same PR.
    doc = _read(INSTALL_DOC)
    assert "No Homebrew formula exists yet for `@github/copilot`" in doc


def test_workflow_does_not_use_curl_pipe_bash():
    """The project's install policy: never document/automate curl|bash or irm|iex installers."""
    wf = _read(WORKFLOW)
    lowered = wf.lower()
    assert "curl" not in lowered
    assert "| bash" not in lowered and "iex (" not in lowered


def test_workflow_has_a_schedule_not_just_every_push():
    """These jobs hit external registries/casks we don't control — see the workflow's own
    header comment for why this runs on a schedule + manual dispatch rather than every push."""
    wf = _read(WORKFLOW)
    assert "schedule:" in wf
    assert "workflow_dispatch:" in wf


def test_gemini_deprecation_watch_job_present():
    """gemini-cli's brew formula is listed deprecated (disable date 2026-12-18) — this job
    exists to fail loudly the day it's actually removed. See claude-tasks.md T-18."""
    wf = _read(WORKFLOW)
    doc = _read(INSTALL_DOC)
    assert "gemini-brew-deprecation-watch" in wf
    assert "2026-12-18" in doc
