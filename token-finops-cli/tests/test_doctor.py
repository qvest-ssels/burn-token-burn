"""`token-finops doctor` — the "why is my report empty?" diagnostic.

Everything runs against the isolated `home` fixture, so no real telemetry and
no real `$HOME` path ever reaches these assertions.
"""
from __future__ import annotations

import os
import subprocess
import sys

from conftest import _TOOL_ENV, NOW, build_claude_tree, write_copilot_db

from token_finops_cli.doctor import cmd_doctor, diagnose, probe_paths, render
from token_finops_cli.adapters import all_adapters

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _args(tool=None):
    class A:
        pass

    a = A()
    a.tool = tool
    return a


def _adapter(tool):
    return next(a for a in all_adapters() if a.tool == tool)


def _status_of(out: str, display: str) -> str:
    """The bracketed status printed on the line naming this adapter."""
    for line in out.splitlines():
        if display in line and line.strip().startswith("["):
            return line.strip().split("]")[0].lstrip("[")
    raise AssertionError(f"{display} not present in doctor output:\n{out}")


# --------------------------------------------------------------------------- #
# all-empty state: fresh machine, no coding agent data anywhere
# --------------------------------------------------------------------------- #
def test_all_missing_on_a_fresh_home(home):
    out = cmd_doctor(_args())

    # every one of the nine adapters is reported, all as missing
    assert len(all_adapters()) == 9
    for ad in all_adapters():
        assert _status_of(out, ad.display_name) == "missing"
    assert "summary: 0 with data, 0 installed but no usage yet, 9 not found" in out
    assert "Nothing to report on yet" in out


def test_fresh_home_prints_versions_and_synth_footer(home):
    out = cmd_doctor(_args())
    assert "token-finops-cli" in out
    assert f"Python {sys.version_info.major}.{sys.version_info.minor}" in out
    # the escape hatch: demo data you can run right now
    assert "token-finops synth --out ./demo-home --scenario steady" in out
    assert "token-finops report" in out


def test_every_adapter_reports_at_least_one_probed_path(home):
    out = cmd_doctor(_args())
    assert out.count("probed:") >= len(all_adapters())
    for ad in all_adapters():
        assert probe_paths(ad), f"{ad.tool} probed nothing"


def test_hint_is_actionable_for_each_missing_tool(home):
    """Every missing tool gets a tool-specific hint, not the generic fallback."""
    for ad in all_adapters():
        d = diagnose(ad)
        assert d.status == "missing"
        assert d.hint
        assert "Not found on this machine" not in d.hint, f"{ad.tool} fell back to the generic hint"


# --------------------------------------------------------------------------- #
# mixed state: some found, some installed-but-empty, some missing
# --------------------------------------------------------------------------- #
def test_mixed_found_empty_missing(home, monkeypatch):
    # found: Copilot has usage rows, Claude Code has transcripts
    db = home / ".copilot" / "session-store.db"
    db.parent.mkdir(parents=True)
    write_copilot_db(db, [{"ts": NOW, "session": "s1"}])
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    build_claude_tree(home / ".claude", now=NOW)

    # empty: the tools' data dirs exist but hold no usage
    (home / ".codex" / "sessions").mkdir(parents=True)
    (home / ".gemini" / "tmp").mkdir(parents=True)
    (home / ".continue" / "sessions").mkdir(parents=True)

    out = cmd_doctor(_args())

    assert _status_of(out, "GitHub Copilot CLI") == "found"
    assert _status_of(out, "Claude Code") == "found"
    assert _status_of(out, "OpenAI Codex CLI") == "empty"
    assert _status_of(out, "Gemini CLI") == "empty"
    assert _status_of(out, "Continue.dev") == "empty"
    assert _status_of(out, "Hermes Agent") == "missing"
    assert _status_of(out, "OpenCode / Kilo CLI") == "missing"
    assert _status_of(out, "Aider") == "missing"
    assert "summary: 2 with data, 3 installed but no usage yet, 4 not found" in out
    assert "Nothing to report on yet" not in out

    # a found adapter reports how much it found, an empty one says "run it once"
    copilot = diagnose(_adapter("copilot"))
    assert copilot.status == "found" and copilot.events == 1 and copilot.latest == NOW
    assert "--budget" in copilot.hint          # found -> next step, not an install hint
    assert "run `codex` once" in diagnose(_adapter("codex")).hint


def test_empty_vs_missing_hinges_on_the_data_dir(home):
    assert diagnose(_adapter("codex")).status == "missing"
    (home / ".codex").mkdir()
    assert diagnose(_adapter("codex")).status == "empty"


def test_aider_is_missing_although_its_search_root_exists(home, monkeypatch):
    """Aider's default search root is `~`, which always exists — presence has to
    come from an Aider-owned path, not from the root being there."""
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_DIRS", str(home))
    analytics = home / ".aider" / "analytics.jsonl"
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_ANALYTICS", str(analytics))

    assert diagnose(_adapter("aider")).status == "missing"

    analytics.parent.mkdir(parents=True)
    analytics.write_text("", encoding="utf-8")
    assert diagnose(_adapter("aider")).status == "empty"


def test_tool_filter_restricts_the_diagnosis(home):
    out = cmd_doctor(_args(tool=["codex"]))
    assert "OpenAI Codex CLI" in out
    assert "Claude Code" not in out
    assert "summary: 0 with data, 0 installed but no usage yet, 1 not found" in out


def test_a_corrupt_store_is_a_note_not_a_crash(home, monkeypatch):
    """A broken data store degrades to a per-tool note; doctor still renders."""
    ad = _adapter("codex")
    (home / ".codex").mkdir()

    def boom(since=None):
        raise OSError("Permission denied")

    monkeypatch.setattr(ad, "events", boom)
    d = diagnose(ad)
    assert d.status == "empty"
    assert "scan failed: OSError" in d.note
    assert "scan failed: OSError" in render([d])


def test_paths_are_rendered_with_a_tilde_not_the_real_home(home):
    out = cmd_doctor(_args())
    assert "probed: ~/.codex" in out
    probed = [ln for ln in out.splitlines() if "probed:" in ln]
    assert probed and all(str(home) not in ln for ln in probed)


# --------------------------------------------------------------------------- #
# exit code: doctor is a diagnostic, never a pass/fail check
# --------------------------------------------------------------------------- #
def test_exit_code_is_zero_with_no_data(home, run_cli):
    out = run_cli("doctor")          # main() returns instead of raising SystemExit
    assert "summary:" in out


def test_subprocess_exit_code_is_zero_on_an_empty_home(tmp_path):
    """Even with nothing installed at all, `doctor` exits 0 — an empty machine
    is a normal state, not a failure."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in _TOOL_ENV}
    env |= {
        "PYTHONPATH": _SRC + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "HOME": str(fake_home),
        "USERPROFILE": str(fake_home),
        "CLAUDE_CONFIG_DIR": str(fake_home / ".claude"),
        "XDG_DATA_HOME": str(fake_home / ".local" / "share"),
        "TOKEN_FINOPS_AIDER_DIRS": str(fake_home / "no-aider"),
        "TOKEN_FINOPS_CLINE_DIRS": str(fake_home / "no-cline"),
    }
    result = subprocess.run([sys.executable, "-m", "token_finops_cli.cli", "doctor"],
                            capture_output=True, text=True, check=False, env=env)
    assert result.returncode == 0
    assert "summary: 0 with data" in result.stdout


def test_doctor_help_runs():
    result = subprocess.run([sys.executable, "-m", "token_finops_cli.cli", "doctor", "--help"],
                            capture_output=True, text=True, check=False,
                            env={**os.environ, "PYTHONPATH": _SRC + os.pathsep + os.environ.get("PYTHONPATH", "")})
    assert result.returncode == 0
    assert "--tool" in result.stdout
