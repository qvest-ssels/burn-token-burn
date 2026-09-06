"""Tests for the unified synthetic telemetry generator (token_finops_cli.synth).

Each tool is generated once, pointed at via `env_for()`, and scanned through
its real adapter -- proving the on-disk shapes `synth.generate()` writes are
exactly what each adapter's `scan()`/`quota()` expects.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from token_finops_cli.adapters import all_adapters
from token_finops_cli.adapters.base import registry
from token_finops_cli.core.runway import compute_runway
from token_finops_cli.synth import ALL_TOOLS, generate
from token_finops_cli.synth.env import env_for


def _apply_env(monkeypatch, out_dir) -> None:
    for var, val in env_for(str(out_dir)).items():
        monkeypatch.setenv(var, val)
    # QUOTA_FILE/QUOTA_HISTORY_FILE are module-level constants resolved from
    # HOME at import time (see synth.env's docstring) -- point them at the
    # synthetic tree explicitly, exactly like tests/conftest.py's `home`
    # fixture does.
    from token_finops_cli.adapters import claude_code
    monkeypatch.setattr(claude_code, "QUOTA_FILE", str(out_dir / ".token-finops" / "quota.json"))
    monkeypatch.setattr(claude_code, "QUOTA_HISTORY_FILE",
                       str(out_dir / ".token-finops" / "quota_history.jsonl"))


def _adapter_for(tool: str):
    return next(a for a in all_adapters() if a.tool == tool)


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_each_tool_scans_with_events(tmp_path, monkeypatch, tool):
    out = tmp_path / "home"
    manifest = generate(str(out), tools=[tool], days=10, seed=7)
    assert manifest[tool]["events"] > 0
    _apply_env(monkeypatch, out)

    adapter = _adapter_for(tool)
    assert adapter.available(), f"{tool} adapter did not detect synthetic data at {adapter.root}"
    events = adapter.events()
    assert events, f"{tool} adapter scanned zero events"
    for ev in events:
        assert ev.model_norm  # models normalise to *something*, never raises
    # USD estimate should be present for at least one non-local event on
    # every tool except Copilot (billed in AI units, not USD) and Codex/
    # Claude Code (see below -- USD is on the events too, just check loosely).
    if tool != "copilot":
        assert any(ev.usd_estimate is not None for ev in events if not ev.is_local_model)


def test_registry_has_every_synth_tool():
    # aider/continue register under "aider"/"continue" -- make sure the
    # tool-name mapping synth.generate() uses lines up with adapters/__init__.
    all_adapters()  # populate registry
    assert set(ALL_TOOLS) <= set(registry)


def test_print_env_contains_every_var(tmp_path, run_cli):
    out = tmp_path / "home"
    output = run_cli("synth", "--out", str(out), "--tools", "copilot", "--print-env")
    for var in env_for(str(out)):
        assert f"export {var}=" in output


def test_synth_cli_manifest_lists_requested_tools(tmp_path, run_cli):
    out = tmp_path / "home"
    output = run_cli("synth", "--out", str(out), "--tools", "copilot,hermes", "--days", "5")
    assert "copilot" in output
    assert "hermes" in output
    assert "codex" not in output


# --------------------------------------------------------------------------- #
# Scenario-specific assertions
# --------------------------------------------------------------------------- #
def test_exhausted_scenario_makes_copilot_critical_or_exhausted(tmp_path, monkeypatch):
    out = tmp_path / "home"
    generate(str(out), tools=["copilot"], days=20, scenario="exhausted", seed=3)
    _apply_env(monkeypatch, out)

    adapter = _adapter_for("copilot")
    policy = adapter.default_policy()
    events = adapter.events()
    rw = compute_runway(events, policy)
    assert rw.status.value in ("CRITICAL", "EXHAUSTED")


def test_burst_scenario_ema_exceeds_cycle_average(tmp_path, monkeypatch):
    # Late in the month so the calendar-month window has many *elapsed* days
    # for the average to dilute across, while EMA still weights the last
    # couple of burst days most heavily.
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    out = tmp_path / "home"
    generate(str(out), tools=["copilot"], days=25, scenario="burst", seed=5, now=now)
    _apply_env(monkeypatch, out)

    adapter = _adapter_for("copilot")
    policy = adapter.default_policy()
    events = adapter.events()
    rw = compute_runway(events, policy, now=now)
    assert rw.burn_per_day_ema is not None and rw.burn_per_day_avg is not None
    assert rw.burn_per_day_ema > rw.burn_per_day_avg


def test_subagent_heavy_raises_claude_code_subagent_share(tmp_path, monkeypatch):
    out = tmp_path / "home"
    manifest = generate(str(out), tools=["claude_code"], days=14, scenario="subagent-heavy", seed=9)
    _apply_env(monkeypatch, out)

    adapter = _adapter_for("claude_code")
    events = adapter.events()
    subs = [e for e in events if e.agent_id]
    assert len(subs) / len(events) > 0.4
    assert manifest["claude_code"]["events"] > 0


def test_weekend_scenario_skips_weekend_days(tmp_path, monkeypatch):
    out = tmp_path / "home"
    generate(str(out), tools=["copilot"], days=21, scenario="weekend", seed=11)
    _apply_env(monkeypatch, out)

    adapter = _adapter_for("copilot")
    events = adapter.events()
    assert events
    assert all(ev.ts_utc.weekday() < 5 for ev in events)


def test_report_compact_lists_every_generated_tool(tmp_path, run_cli, monkeypatch):
    out = tmp_path / "home"
    generate(str(out), days=10, seed=1)
    _apply_env(monkeypatch, out)

    output = run_cli("report", "--compact")
    for tool in ALL_TOOLS:
        adapter = _adapter_for(tool)
        if adapter.available():
            assert adapter.display_name in output
