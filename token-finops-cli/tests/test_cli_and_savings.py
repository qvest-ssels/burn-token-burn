"""cli.py end to end (in-process, isolated HOME) plus the savings/break-even
estimator. Subprocess smoke tests for the `python -m token_finops_cli` entry
point live at the bottom."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from conftest import build_claude_tree, transcript_line, write_copilot_db, write_transcript

from token_finops_cli import cli
from token_finops_cli.cli import _normalize_argv, _runway_json, _since, build_parser
from token_finops_cli.core.model import Status
from token_finops_cli.savings import (LocalCost, add_savings_parsers, cloud_blended_usd_per_mtok, cmd_break_even,
                                      cmd_savings, energy, hardware_profiles, local_cost)

REAL_NOW = datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# argv handling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("argv, expected", [
    ([], ["report"]),
    (["--json"], ["report", "--json"]),
    (["-c", "--since", "30d"], ["report", "-c", "--since", "30d"]),
    (["report", "--json"], ["report", "--json"]),
    (["sessions", "--totals"], ["sessions", "--totals"]),
    (["self-audit"], ["self-audit"]),
    (["collect-statusline"], ["collect-statusline"]),
    (["adapters"], ["adapters"]),
    (["savings", "--list"], ["savings", "--list"]),
    (["break-even"], ["break-even"]),
    (["-h"], ["-h"]),
    (["--help"], ["--help"]),
])
def test_normalize_argv(argv, expected):
    assert _normalize_argv(argv) == expected


def test_since_map():
    assert _since("all") is None
    assert abs((_since("7d") - (REAL_NOW - timedelta(days=7))).total_seconds()) < 5
    assert abs((_since("1d") - (REAL_NOW - timedelta(days=1))).total_seconds()) < 5
    with pytest.raises(KeyError):
        _since("2d")


def test_build_parser_defaults_and_tool_choices(home):
    from token_finops_cli.adapters import all_adapters
    all_adapters()  # populate the registry that feeds --tool choices
    p = build_parser()
    r = p.parse_args(["report"])
    assert (r.since, r.cycle_day, r.compact, r.json, r.watch, r.budget, r.allowance, r.tool) == \
        ("7d", 1, False, False, None, None, None, None)
    r = p.parse_args(["report", "--tool", "copilot", "--tool", "claude_code", "-c"])
    assert r.tool == ["copilot", "claude_code"] and r.compact
    with pytest.raises(SystemExit):
        p.parse_args(["report", "--tool", "no-such-tool"])
    s = p.parse_args(["sessions"])
    assert (s.since, s.limit, s.totals, s.session, s.gap_minutes) == ("all", 20, False, None, 30.0)
    a = p.parse_args(["self-audit"])
    assert a.session == "latest" and a.config_dir == os.environ["CLAUDE_CONFIG_DIR"]
    b = p.parse_args(["break-even", "--since", "90d", "--tool", "claude_code"])
    assert b.since == "90d" and b.tool == ["claude_code"] and b.replaceable_tiers == "haiku,sonnet"
    with pytest.raises(SystemExit):
        p.parse_args(["break-even", "--since", "7d"])


def test_help_exits_zero(run_cli, capsys):
    with pytest.raises(SystemExit) as ex:
        run_cli("--help")
    assert ex.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("report", "sessions", "self-audit", "savings", "break-even", "collect-statusline", "adapters"):
        assert cmd in out


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def _copilot_rows(n=6, aiu=100.0, minutes_ago=5, session="s1"):
    return [{"ts": REAL_NOW - timedelta(minutes=minutes_ago + i), "session": session, "inp": 1000, "out": 200,
             "nano_aiu": int(aiu * 1e9)} for i in range(n)]


@pytest.fixture
def copilot_db(home, monkeypatch):
    db = home / "copilot.db"
    write_copilot_db(db, _copilot_rows())
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    return db


def test_report_no_data(home, run_cli):
    assert run_cli("report") == "No supported tool data found. Run `token-finops adapters` to see what was probed.\n"
    assert run_cli() == run_cli("report")


def test_report_json_shape_on_synthetic_copilot(copilot_db, run_cli):
    data = json.loads(run_cli("report", "--json", "--budget", "1500"))
    assert len(data) == 1
    d = data[0]
    assert set(d) == {"tool", "display_name", "window", "unit", "used", "allowance", "used_fraction",
                      "time_fraction", "pace_ratio", "burn_per_day_avg", "burn_per_day_ema", "runway_days",
                      "days_left", "resets_at", "status", "notes"}
    assert d["tool"] == "copilot" and d["display_name"] == "GitHub Copilot CLI"
    assert d["window"] == "month" and d["unit"] == "aiu"
    assert d["used"] == pytest.approx(600.0) and d["allowance"] == 1500.0
    assert d["used_fraction"] == pytest.approx(0.4)
    assert 0 < d["time_fraction"] <= 1 and d["pace_ratio"] == pytest.approx(0.4 / d["time_fraction"])
    assert d["burn_per_day_avg"] > 0 and d["burn_per_day_ema"] > 0
    assert d["runway_days"] > 0 and d["days_left"] > 0
    assert d["resets_at"].startswith(f"{REAL_NOW.year}-") or d["resets_at"].startswith(f"{REAL_NOW.year + 1}-")
    assert d["status"] in [s.value for s in Status] and d["notes"] == []


def test_report_default_budget_and_cycle_day(copilot_db, run_cli):
    d = json.loads(run_cli("report", "--json"))[0]
    assert d["allowance"] == 20_000.0  # DEFAULT_BUDGET_AIU: the largest real individual plan (Max)
    d15 = json.loads(run_cli("report", "--json", "--cycle-day", "15"))[0]
    assert d15["resets_at"].endswith("-15 00:00:00+00:00")


def test_report_text_since_label_and_sections(copilot_db, run_cli):
    out = run_cli("report", "--budget", "1500")
    lines = out.splitlines()
    assert lines[0] == "GitHub Copilot CLI (last 7d):"
    assert "  calls:            6  (sessions 1, sub-agents 0)" in lines
    assert "GitHub Copilot CLI — window: month (resets " in out
    assert "  used:     600.0 / 1,500.0 AI units" in lines
    assert "binding constraint" not in out                       # single tool
    assert run_cli("report", "--since", "30d").startswith("GitHub Copilot CLI (last 30d):")
    assert run_cli("report", "--since", "all").startswith("GitHub Copilot CLI (all time):")


def test_report_since_filters_summary_but_not_runway(home, run_cli, monkeypatch):
    db = home / "c.db"
    rows = _copilot_rows(2) + _copilot_rows(3, minutes_ago=3 * 24 * 60, session="old")
    write_copilot_db(db, rows)
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    out = run_cli("report", "--since", "1d", "--budget", "1000")
    assert "  calls:            2  (sessions 1, sub-agents 0)" in out
    # the runway still counts everything in the billing cycle that is not before the cycle start
    used = next(ln for ln in out.splitlines() if ln.startswith("  used:"))
    cycle_start = REAL_NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    expected = 500.0 if REAL_NOW - timedelta(days=3) >= cycle_start else 200.0
    assert used == f"  used:     {expected:,.1f} / 1,000.0 AI units"


def test_report_db_path_routes_to_copilot_only(home, run_cli):
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    db = home / "elsewhere.db"
    write_copilot_db(db, _copilot_rows())
    assert "Claude Code" in run_cli("report")                     # both tools without --db-path
    out = run_cli("report", "--db-path", str(db))
    assert out.startswith("GitHub Copilot CLI (last 7d):")
    assert "Claude Code" not in out
    assert os.environ["TOKEN_FINOPS_COPILOT_DB"] == str(db)


def test_report_compact_one_line_per_tool(copilot_db, home, run_cli):
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    out = run_cli("report", "--compact", "--budget", "1500")
    lines = out.rstrip("\n").split("\n")
    tool_lines = [ln for ln in lines if ln.startswith(("GitHub Copilot CLI", "Claude Code"))]
    assert len(tool_lines) == 2 and len(lines) == 4
    copilot = next(ln for ln in tool_lines if ln.startswith("GitHub Copilot CLI"))
    assert "[########------------]  40.0%" in copilot
    claude = next(ln for ln in tool_lines if ln.startswith("Claude Code"))
    assert claude.endswith("runway    n/a  ?")
    # only Copilot has a runway, so it is the binding constraint
    assert lines[-1].startswith("binding constraint: GitHub Copilot CLI (month) — runway ")
    status = json.loads(run_cli("report", "--json", "--budget", "1500", "--tool", "copilot"))[0]["status"]
    assert lines[-1].endswith(f"-> {status}")
    assert copilot.endswith({"OK": "OK", "WARN": "WARN", "CRITICAL": "CRIT"}[status])


def test_report_tool_filter_and_allowance(copilot_db, home, run_cli):
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    data = json.loads(run_cli("report", "--json", "--tool", "claude_code", "--allowance", "0.5"))
    assert [d["tool"] for d in data] == ["claude_code"]
    assert data[0]["allowance"] == 0.5 and data[0]["status"] == "UNKNOWN"
    assert data[0]["notes"][0].startswith("percent-based budget without provider snapshot")
    both = json.loads(run_cli("report", "--json", "--tool", "claude_code", "--tool", "copilot"))
    assert {d["tool"] for d in both} == {"claude_code", "copilot"}


def test_report_binding_constraint_across_tools(copilot_db, home, run_cli):
    """Copilot has a month of runway; Claude Code (from two snapshots) has hours -> Claude binds."""
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    d = home / ".token-finops"
    d.mkdir()
    resets = (REAL_NOW + timedelta(hours=2)).isoformat()
    snaps = [{"observed_at": (REAL_NOW - timedelta(hours=1)).isoformat(),
              "rate_limits": {"five_hour": {"used_percentage": 20, "resets_at": resets}}},
             {"observed_at": (REAL_NOW - timedelta(minutes=1)).isoformat(),
              "rate_limits": {"five_hour": {"used_percentage": 60, "resets_at": resets}}}]
    (d / "quota_history.jsonl").write_text("\n".join(json.dumps(s) for s in snaps) + "\n")
    (d / "quota.json").write_text(json.dumps(snaps[-1]))
    out = run_cli("report", "--budget", "1_000_000".replace("_", ""))
    last = out.splitlines()[-1]
    assert last.startswith("binding constraint: Claude Code (5h) — runway ") and last.endswith("-> CRITICAL")
    assert "  burn:     " in out and "% per hour (from snapshots)" in out


def test_report_json_runway_none_serialises_as_null(copilot_db, home, run_cli):
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    d = json.loads(run_cli("report", "--json", "--tool", "claude_code"))[0]
    assert d["runway_days"] is None and d["resets_at"] is None


def test_report_json_is_strict_json_without_usage_in_cycle(home, run_cli, monkeypatch):
    db = home / "old.db"
    last_month = REAL_NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
    write_copilot_db(db, [{"ts": last_month, "nano_aiu": 10**11}])
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    out = run_cli("report", "--json")

    def reject(token):
        raise ValueError(f"non-standard JSON token {token}")

    data = json.loads(out, parse_constant=reject)
    assert data[0]["runway_days"] is None or isinstance(data[0]["runway_days"], (int, float))


def test_runway_json_mirrors_runway(home):
    from conftest import NOW, make_event, month_policy
    from token_finops_cli.core.runway import compute_runway
    rw = compute_runway([make_event(1, aiu=10.0)], month_policy(100.0), now=NOW)
    ad = SimpleNamespace(tool="copilot", display_name="X")
    d = _runway_json(ad, rw)
    assert d["used"] == 10.0 and d["status"] == "OK" and d["resets_at"] == rw.resets_at
    assert d["window"] == "month" and d["unit"] == "aiu"


def test_report_watch_redraws_until_interrupted(copilot_db, run_cli, monkeypatch):
    calls = []

    def fake_sleep(s):
        calls.append(s)
        if len(calls) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", fake_sleep)
    out = run_cli("report", "--watch", "7", "--compact")
    assert calls == [7.0, 7.0]
    assert out.count("\033[2J\033[H") == 2
    assert out.count("(refreshing every 7s, Ctrl+C to stop)") == 2
    assert out.count("GitHub Copilot CLI") == 2


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #
def test_sessions_table_default(copilot_db, home, run_cli):
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    out = run_cli("sessions")
    lines = out.splitlines()
    idx = lines.index("GitHub Copilot CLI sessions (all time):")
    assert lines[idx + 1].split()[:2] == ["session", "calls"]
    assert lines[idx + 2].split()[:2] == ["s1", "6"]
    idx = lines.index("Claude Code sessions (all time):")
    assert lines[idx + 2].split()[:2] == ["sess-1", "11"]
    assert out.endswith("\n\n")                       # blank line after each tool block


def test_sessions_since_limit_and_empty(home, run_cli, monkeypatch):
    db = home / "c.db"
    write_copilot_db(db, _copilot_rows(2) + _copilot_rows(3, minutes_ago=10 * 24 * 60, session="old"))
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    out = run_cli("sessions", "--since", "7d")
    assert out.startswith("GitHub Copilot CLI sessions (last 7d):")
    assert "old" not in out and " s1 " in out
    out = run_cli("sessions", "--limit", "1")
    assert len([ln for ln in out.splitlines() if ln.startswith("  ") and "session" not in ln]) == 1
    assert run_cli("sessions", "--since", "1d", "--tool", "claude_code") == "No sessions found.\n"


def test_sessions_available_tool_without_events(home, run_cli, monkeypatch):
    import sqlite3
    db = home / "empty.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE assistant_usage_events (session_id TEXT, created_at TEXT, input_tokens INTEGER, "
                "output_tokens INTEGER, reasoning_tokens INTEGER, duration_ms REAL, total_nano_aiu INTEGER)")
    con.commit()
    con.close()
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    assert run_cli("sessions") == "No sessions found.\n"
    # report still shows the (empty) tool with an infinite runway
    out = run_cli("report", "--budget", "100")
    assert "  runway:   inf vs " in out and "-> OK" in out


def test_sessions_db_path_routes_to_copilot(home, run_cli):
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    db = home / "x.db"
    write_copilot_db(db, _copilot_rows())
    out = run_cli("sessions", "--db-path", str(db))
    assert out.startswith("GitHub Copilot CLI sessions") and "Claude Code" not in out


def test_sessions_legacy_totals_and_detail(home, run_cli):
    db = home / "x.db"
    rows = _copilot_rows(3, minutes_ago=200) + _copilot_rows(3, minutes_ago=5)   # a 3h+ break in between
    write_copilot_db(db, rows)
    out = run_cli("sessions", "--totals", "--db-path", str(db))
    lines = out.splitlines()
    assert lines[0] == "All sessions report (all time):"
    assert "  sessions:        1" in lines and "  requests:        6" in lines
    assert "  input tokens:    6.0k" in lines and "  total tokens:    7.2k" in lines
    assert "  total breaks detected: 1" in lines
    assert any("active time (gaps < 30m), summed across all sessions:" in ln for ln in lines)

    out = run_cli("sessions", "--session", "s1", "--db-path", str(db), "--gap-minutes", "60")
    lines = out.splitlines()
    assert lines[0] == "Session s1:"
    assert "  requests:        6" in lines and "  breaks detected: 1" in lines
    assert "  active time (gaps < 60m):   4m00s" in lines
    assert "  idle/paused time (gaps >= 60m): 3h13m00s" in lines
    assert "  Breaks (pause start -> resume, duration):" in lines
    assert run_cli("sessions", "--session", "nope", "--db-path", str(db)) == "No events found for session nope\n"


def test_sessions_legacy_uses_token_finops_db_env(home, run_cli, monkeypatch):
    db = home / "env.db"
    write_copilot_db(db, _copilot_rows(2))
    monkeypatch.setenv("TOKEN_FINOPS_DB", str(db))
    assert run_cli("sessions", "--totals").startswith("All sessions report (all time):")


# --------------------------------------------------------------------------- #
# adapters
# --------------------------------------------------------------------------- #
def test_adapters_listing(copilot_db, home, run_cli):
    out = run_cli("adapters")
    lines = out.splitlines()
    assert lines[0].split() == ["tool", "found", "root"]
    rows = {ln.split()[0]: ln.split()[1:] for ln in lines[1:]}
    assert rows["copilot"][0] == "yes" and rows["copilot"][1] == str(copilot_db)
    assert rows["claude_code"][0] == "no" and rows["claude_code"][1].endswith("/.claude/projects")
    for tool in ("codex", "gemini_cli", "hermes"):
        assert tool in rows and rows[tool][0] == "no"
    assert all(len(v) >= 2 for v in rows.values())


# --------------------------------------------------------------------------- #
# savings: formulas
# --------------------------------------------------------------------------- #
def _lc(**kw) -> LocalCost:
    base = dict(hardware="hw", model="m", tok_s=25.0, load_w=90.0, price_usd=3999.0, lifetime_years=3.0,
                utilization=0.2, tariff="t", eur_per_kwh=0.37, eur_per_usd=0.92)
    base.update(kw)
    return LocalCost(**base)


def test_local_cost_formulas():
    lc = _lc()
    assert lc.hours_per_mtok == pytest.approx(1e6 / (25 * 3600))                 # 11.11 h
    assert lc.kwh_per_mtok == pytest.approx(90 * lc.hours_per_mtok / 1000)        # 1.0 kWh
    assert lc.wh_per_1k_tok == lc.kwh_per_mtok
    assert lc.energy_usd_per_mtok == pytest.approx(lc.kwh_per_mtok * 0.37 / 0.92)
    assert lc.capex_usd_per_hour == pytest.approx(3999 / (3 * 365 * 24 * 0.2))
    assert lc.capex_usd_per_mtok == pytest.approx(lc.capex_usd_per_hour * lc.hours_per_mtok)
    assert lc.total_usd_per_mtok == pytest.approx(lc.energy_usd_per_mtok + lc.capex_usd_per_mtok)
    # doubling throughput halves both energy and capex per token
    fast = _lc(tok_s=50.0)
    assert fast.total_usd_per_mtok == pytest.approx(lc.total_usd_per_mtok / 2)
    # utilisation only touches capex
    busy = _lc(utilization=1.0)
    assert busy.energy_usd_per_mtok == lc.energy_usd_per_mtok
    assert busy.capex_usd_per_mtok == pytest.approx(lc.capex_usd_per_mtok / 5)
    assert _lc(utilization=0.0).capex_usd_per_hour == pytest.approx(3999 / (3 * 365 * 24 * 1e-6))


def test_break_even_utilization():
    lc = _lc()
    cloud = 3.2
    be = lc.break_even_utilization(cloud)
    assert be is not None
    at_be = _lc(utilization=be)
    assert at_be.total_usd_per_mtok == pytest.approx(cloud)                  # definition of break-even
    assert lc.break_even_utilization(1e9) == pytest.approx(0.0, abs=1e-6)     # absurdly expensive cloud
    assert lc.break_even_utilization(lc.energy_usd_per_mtok + 0.001) == 1.0   # capped at 24/7
    assert lc.break_even_utilization(lc.energy_usd_per_mtok) is None          # margin == 0
    assert _lc(load_w=100_000).break_even_utilization(cloud) is None          # energy alone exceeds cloud


def test_local_cost_from_profiles_and_solar_cheaper_than_grid(home):
    lc = local_cost("mac-studio-m4-max-128gb", "qwen3-32b", "grid-de-household", utilization=0.2)
    assert (lc.tok_s, lc.load_w, lc.price_usd, lc.eur_per_kwh, lc.eur_per_usd) == (25.0, 90.0, 3999.0, 0.37, 0.92)
    assert lc.hardware == "mac-studio-m4-max-128gb" and lc.model == "qwen3-32b" and lc.tariff == "grid-de-household"
    solar = local_cost("mac-studio-m4-max-128gb", "qwen3-32b", "solar-de-feed-in")
    assert 0 < solar.energy_usd_per_mtok < lc.energy_usd_per_mtok
    assert solar.capex_usd_per_mtok == lc.capex_usd_per_mtok
    hi = local_cost("mac-studio-m4-max-128gb", "qwen3-32b", "grid-de-household", utilization=0.8)
    assert hi.total_usd_per_mtok < lc.total_usd_per_mtok
    with pytest.raises(KeyError, match="no throughput figure"):
        local_cost("mac-mini-m4-pro-64gb", "qwen3-235b-a22b")
    with pytest.raises(KeyError):
        local_cost("no-such-box", "qwen3-32b")


def test_cloud_blended_usd_per_mtok(home):
    assert cloud_blended_usd_per_mtok("sonnet") == pytest.approx(2.0 * 0.85 + 10.0 * 0.15)
    assert cloud_blended_usd_per_mtok("haiku", output_share=0.0) == pytest.approx(1.0)
    assert cloud_blended_usd_per_mtok("haiku", output_share=1.0) == pytest.approx(5.0)
    assert cloud_blended_usd_per_mtok("fable", 0.5) == pytest.approx(30.0)
    with pytest.raises(KeyError):
        cloud_blended_usd_per_mtok("gpt")


def test_profile_files_are_consistent(home):
    hw, en = hardware_profiles(), energy()
    for name, m in hw["models"].items():
        if name.startswith("_"):
            continue
        assert m["quality_tier"] in en["cloud_tiers_usd_per_mtok"]
        assert set(m["tok_s"]) <= set(hw["hardware"])
    assert set(en["co2_g_per_kwh"]) <= set(en["tariffs"])
    assert hw["_review_date"] and en["_review_date"]


def _energy_override(home, monkeypatch, **changes):
    data = json.loads(open(os.path.join(os.path.dirname(cli.__file__), "savings", "energy.json")).read())
    for k, v in changes.items():
        data[k] = v
    p = home / "energy.json"
    p.write_text(json.dumps(data))
    monkeypatch.setenv("TOKEN_FINOPS_ENERGY_JSON", str(p))
    return data


def test_energy_override_env(home, monkeypatch):
    _energy_override(home, monkeypatch, eur_per_usd=1.0)
    assert energy()["eur_per_usd"] == 1.0
    assert local_cost("mac-studio-m4-max-128gb", "qwen3-32b").eur_per_usd == 1.0


# --------------------------------------------------------------------------- #
# savings: CLI
# --------------------------------------------------------------------------- #
def test_cmd_savings_cloud_cheaper_at_low_utilisation(home, run_cli):
    out = run_cli("savings")
    lines = out.splitlines()
    assert lines[0] == "Local inference: Mac Studio M4 Max, 128 GB + Qwen3 32B (Q4)"
    assert "  throughput:        25 tok/s  ->  11.11 h per 1M tokens" in lines
    assert "  energy:            90 W load  ->  1.00 Wh per 1k tok, 1.00 kWh per 1M tok" in lines
    assert "  energy cost:       $0.40 / 1M tok" in lines
    assert "  capex:             $3,999 over 3 y at 20% utilisation = $0.761/h -> $8.45 / 1M tok" in lines
    assert "  local total:       $8.86 / 1M tok" in lines
    assert "Cloud comparison (sonnet-class, 15% output tokens): $3.20 / 1M tok  (Claude Sonnet 5)" in lines
    assert "  -> local is 2.77x the cloud price: CLOUD CHEAPER" in lines
    assert any(ln.startswith("  -> break-even utilisation: 6") and "h/day of inference)" in ln for ln in lines)
    assert "  CO2: ~380 g per 1M tok on this tariff" in lines
    assert lines[-1].startswith("Caveats:") and "sonnet-class local" in lines[-1]


def test_cmd_savings_local_cheaper_at_high_utilisation(home, run_cli):
    out = run_cli("savings", "--utilization", "1.0", "--output-share", "0.3", "--lifetime-years", "4")
    assert "at 100% utilisation" in out and "over 4 y" in out
    assert "Cloud comparison (sonnet-class, 30% output tokens): $4.40 / 1M tok" in out
    assert "LOCAL CHEAPER" in out and "CLOUD CHEAPER" not in out


def test_cmd_savings_solar_and_no_co2_line(home, run_cli, monkeypatch):
    out = run_cli("savings", "--power", "solar-de-feed-in")
    assert "= 0.077 EUR/kWh" in out and "CO2: ~40 g" in out
    _energy_override(home, monkeypatch, co2_g_per_kwh={})
    out = run_cli("savings")
    assert "CO2" not in out


def test_cmd_savings_energy_alone_exceeds_cloud(home, run_cli, monkeypatch):
    data = _energy_override(home, monkeypatch)
    data["tariffs"]["pricey"] = {"eur_per_kwh": 50.0, "label": "Diesel generator"}
    (home / "energy.json").write_text(json.dumps(data))
    out = run_cli("savings", "--power", "pricey", "--utilization", "1.0")
    assert "  tariff:            Diesel generator = 50.000 EUR/kWh" in out
    assert "CLOUD CHEAPER" in out
    assert "  -> energy alone already exceeds the cloud price; no utilisation makes this box win" in out
    assert "break-even utilisation" not in out


def test_cmd_savings_haiku_class_model(home, run_cli):
    out = run_cli("savings", "--hardware", "rtx-4090-workstation", "--model", "qwen3-8b")
    assert "PC + RTX 4090 (24 GB) + Qwen3 8B" in out
    assert "Cloud comparison (haiku-class, 15% output tokens): $1.60 / 1M tok  (Claude Haiku 4.5)" in out


def test_cmd_savings_list(home, run_cli):
    out = run_cli("savings", "--list")
    lines = out.splitlines()
    assert lines[0] == "hardware:" and "models:" in lines and "tariffs:" in lines
    assert any(ln.startswith("  mac-studio-m4-max-128gb") and "($3999, 90 W load)" in ln for ln in lines)
    assert any(ln.startswith("  qwen3-32b") and "~sonnet-class" in ln for ln in lines)
    assert not any("_comment" in ln for ln in lines)
    assert any(ln.startswith("  solar-de-feed-in") and "0.077 EUR/kWh" in ln for ln in lines)


def test_cmd_savings_direct_call_matches_cli(home, run_cli):
    args = SimpleNamespace(hardware="mac-studio-m4-max-128gb", model="qwen3-32b", power="grid-de-household",
                           utilization=0.2, lifetime_years=3.0, output_share=0.15, list=False)
    assert cmd_savings(args) + "\n" == run_cli("savings")


def test_add_savings_parsers_defaults():
    import argparse
    p = argparse.ArgumentParser()
    add_savings_parsers(p.add_subparsers(dest="command"))
    a = p.parse_args(["savings"])
    assert (a.hardware, a.model, a.power, a.utilization, a.lifetime_years, a.output_share, a.list) == \
        ("mac-studio-m4-max-128gb", "qwen3-32b", "grid-de-household", 0.2, 3.0, 0.15, False)
    b = p.parse_args(["break-even"])
    assert (b.replaceable_tiers, b.since, b.tool) == ("haiku,sonnet", "all", None)


# --------------------------------------------------------------------------- #
# break-even
# --------------------------------------------------------------------------- #
def _claude_usage(home, *, old_days=None, today_output=6_000_000, extra_lines=()):
    cfg = home / ".claude"
    lines = [transcript_line(REAL_NOW - timedelta(minutes=30), "m1", "r1", model="claude-sonnet-5", session="s",
                             inp=1000, out=today_output, cr=0, cw=0)]
    if old_days:
        lines.append(transcript_line(REAL_NOW - timedelta(days=old_days), "m0", "r0", model="claude-sonnet-5",
                                     session="s", inp=1000, out=100, cr=0, cw=0))
    lines += list(extra_lines)
    write_transcript(cfg / "projects" / "p" / "s.jsonl", lines)
    return cfg


def _be_args(**kw):
    base = dict(hardware="mac-studio-m4-max-128gb", model="qwen3-32b", power="grid-de-household",
                lifetime_years=3.0, replaceable_tiers="haiku,sonnet", tool=None, since="all")
    base.update(kw)
    return SimpleNamespace(**base)


def test_break_even_no_events_and_no_replaceable(home, run_cli):
    assert run_cli("break-even") == "No usage events found to replay.\n"
    write_transcript(home / ".claude" / "projects" / "p" / "s.jsonl", [
        transcript_line(REAL_NOW, "m1", "r1", model="claude-opus-5", session="s"),
    ])
    assert run_cli("break-even") == "No usage on replaceable tiers (haiku, sonnet) in the selected range.\n"
    # but opus can be declared replaceable
    out = run_cli("break-even", "--replaceable-tiers", "opus")
    assert "replaceable cloud usage (opus-class)" in out


def test_break_even_already_cheaper(home, run_cli):
    _claude_usage(home, today_output=6_000_000)     # $60 of Sonnet output today
    out = run_cli("break-even")
    lines = out.splitlines()
    assert lines[0].startswith("Break-even replay: Mac Studio M4 Max, 128 GB running Qwen3 32B (Q4) since ")
    assert lines[0].endswith("(1 days)")
    assert "  replaceable cloud usage (haiku, sonnet-class): 6.0M tokens = $60.00 API-equivalent" in lines
    local = next(ln for ln in lines if ln.startswith("  local alternative:"))
    assert "energy $2.41 + capex $3.65 ($3.65/day straight-line over 3 y) = $6.07" in local
    verdict = next(ln for ln in lines if ln.startswith("  -> "))
    assert verdict.startswith("  -> LOCAL WOULD ALREADY BE CHEAPER by $53.9")   # 60.00 - 6.07 (rounding)
    assert lines[-1].startswith("Assumptions:")


def test_break_even_never_pays_off_via_energy_override(home, run_cli, monkeypatch):
    _claude_usage(home, today_output=6_000_000)
    data = _energy_override(home, monkeypatch)
    data["tariffs"]["grid-de-household"]["eur_per_kwh"] = 100.0        # 108 $/MTok of electricity
    (home / "energy.json").write_text(json.dumps(data))
    out = run_cli("break-even")
    assert "= $60.00 API-equivalent" in out
    assert "energy $652.28" in out                  # 6.001M tokens * $108.70/MTok
    assert "-> cloud still cheaper by $595.93; at the current pace ($4.29/day) the box never pays off " \
           "within its lifetime" in out


def test_break_even_never_pays_off_with_tiny_usage(home, run_cli):
    _claude_usage(home, today_output=1000)         # a cent of Sonnet
    out = run_cli("break-even")
    assert "the box never pays off within its lifetime" in out
    assert "cloud still cheaper by $3.6" in out


def test_break_even_overtakes_and_since_filter(home, run_cli):
    _claude_usage(home, old_days=60, today_output=6_000_000)
    out = run_cli("break-even")
    assert "since " in out and "(61 days)" in out
    assert "capex $222.78" in out                       # 61 * 3999/1095
    assert "at the last-14-day pace ($4.29/day) local overtakes in ~" in out
    eta_line = next(ln for ln in out.splitlines() if "overtakes in" in ln)
    days = int(eta_line.split("~")[1].split()[0])
    assert 200 < days < 400
    # restricting to 30 days drops the old event: back to "already cheaper"
    out30 = run_cli("break-even", "--since", "30d")
    assert "(1 days)" in out30 and "LOCAL WOULD ALREADY BE CHEAPER" in out30
    assert "(61 days)" in run_cli("break-even", "--since", "90d")


def test_break_even_tool_filter_and_unknown_model_fallback(home, run_cli, monkeypatch):
    fallback = transcript_line(REAL_NOW - timedelta(minutes=5), "m9", "r9", model="haiku-custom-finetune",
                               session="s", inp=1_000_000, out=0, cr=1_000_000, cw=0)
    _claude_usage(home, today_output=1_000_000, extra_lines=[fallback])
    db = home / "c.db"
    write_copilot_db(db, _copilot_rows(3))               # gpt-5: not a replaceable tier, must not count
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    out = run_cli("break-even")
    # $10 sonnet + haiku fallback: 1M input @ $1 + 1M cache read @ 10 % = $1.10
    assert "3.0M tokens = $11.10 API-equivalent" in out
    assert run_cli("break-even", "--tool", "copilot") == \
        "No usage on replaceable tiers (haiku, sonnet) in the selected range.\n"
    assert cmd_break_even(_be_args(tool=["claude_code"])) + "\n" == out


# --------------------------------------------------------------------------- #
# subprocess smoke tests for the module entry point
# --------------------------------------------------------------------------- #
def _run(*args, env=None):
    env = {**os.environ, "PYTHONPATH": "src", **(env or {})}
    return subprocess.run([sys.executable, "-m", "token_finops_cli", *args], capture_output=True, text=True,
                          check=False, env=env)


def test_module_entry_help():
    r = _run("--help")
    assert r.returncode == 0
    for cmd in ("report", "sessions", "self-audit", "savings", "break-even", "collect-statusline", "adapters"):
        assert cmd in r.stdout


def test_module_entry_report_json_on_synthetic_copilot(tmp_path):
    from token_finops_cli.adapters.copilot import build_synthetic_db
    db = tmp_path / "s.db"
    build_synthetic_db(str(db), days=5, events_per_day=4)
    r = _run("report", "--tool", "copilot", "--budget", "5000", "--json", env={"TOKEN_FINOPS_COPILOT_DB": str(db)})
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data[0]["tool"] == "copilot" and data[0]["unit"] == "aiu" and data[0]["used"] > 0
