"""`~/.token-finops/config.json` + `TOKEN_FINOPS_*` overrides (core/config.py).

The contract under test is one sentence long:

    explicit CLI flag > TOKEN_FINOPS_* env var > config.json > hardcoded default

...applied to the budget thresholds, the monthly cycle day, per-tool allowances,
the rolling-window length, and the configurable default tool -- plus the rule that
*real* provider data (a recorded `resets_at`) is never overridden by any of it.

Every test here runs against a throwaway config file (`write_config`) or a
throwaway `$HOME`; the autouse `isolated_config` fixture in conftest guarantees a
developer's own settings can never reach these assertions.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from conftest import build_claude_tree, make_event, write_copilot_db

from token_finops_cli import cli
from token_finops_cli.adapters import all_adapters
from token_finops_cli.core import config
from token_finops_cli.core.model import BudgetPolicy, CycleKind, Status, Unit
from token_finops_cli.core.runway import compute_runway

REAL_NOW = datetime.now(timezone.utc)


@pytest.fixture
def copilot_db(home, monkeypatch):
    """Six Copilot events worth 600 AI units, a few minutes old."""
    db = home / "copilot.db"
    write_copilot_db(db, [{"ts": REAL_NOW - timedelta(minutes=5 + i), "session": "s1",
                           "inp": 1000, "out": 200, "nano_aiu": 100 * 10**9} for i in range(6)])
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    return db


# --------------------------------------------------------------------------- #
# The file itself
# --------------------------------------------------------------------------- #
def test_no_config_file_means_the_historical_defaults():
    """The whole feature is opt-in: nothing on disk == exactly the old behaviour."""
    assert config.load_config() == {}
    assert config.thresholds() == (0.75, 0.90)
    assert config.cycle_day() == 1
    assert config.default_tool(valid={"copilot"}) is None
    assert config.allowance("copilot") is None


@pytest.mark.parametrize("raw", ["{ not json", "[1, 2, 3]", '"a string"', "", "null"])
def test_unparsable_or_non_object_config_is_treated_as_no_settings(tmp_path, monkeypatch, raw):
    path = tmp_path / "config.json"
    path.write_text(raw, encoding="utf-8")
    monkeypatch.setenv("TOKEN_FINOPS_CONFIG", str(path))
    assert config.load_config() == {}
    assert config.thresholds() == (0.75, 0.90)


def test_unreadable_config_does_not_raise(tmp_path, monkeypatch):
    """A directory where a file is expected is the cheap portable stand-in for
    "open() raises OSError"; the loader must swallow it like a missing file."""
    (tmp_path / "config.json").mkdir()
    monkeypatch.setenv("TOKEN_FINOPS_CONFIG", str(tmp_path / "config.json"))
    assert config.load_config() == {}


def test_config_path_defaults_to_the_documented_location(home, monkeypatch):
    monkeypatch.delenv("TOKEN_FINOPS_CONFIG", raising=False)
    assert config.config_path() == str(home / ".token-finops" / "config.json")


# --------------------------------------------------------------------------- #
# Thresholds: config.json / env / default
# --------------------------------------------------------------------------- #
def test_config_json_overrides_the_hardcoded_thresholds(write_config):
    write_config({"budget": {"warn_at": 0.8, "critical_at": 0.95}})
    assert config.thresholds() == (0.8, 0.95)


def test_env_var_overrides_config_json(write_config):
    write_config({"budget": {"warn_at": 0.8, "critical_at": 0.95}})
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TOKEN_FINOPS_WARN_AT", "0.5")
        assert config.thresholds() == (0.5, 0.95)      # env wins, config still supplies critical_at
        mp.setenv("TOKEN_FINOPS_CRITICAL_AT", "0.6")
        assert config.thresholds() == (0.5, 0.6)


def test_empty_env_var_does_not_shadow_config_json(write_config, monkeypatch):
    """`export TOKEN_FINOPS_WARN_AT=` is "unset", not "warn at 0"."""
    write_config({"budget": {"warn_at": 0.8}})
    monkeypatch.setenv("TOKEN_FINOPS_WARN_AT", "")
    assert config.warn_at() == 0.8


@pytest.mark.parametrize("bad", ["nonsense", "1.5", "0", "-0.2", "inf", "nan"])
def test_invalid_threshold_falls_back_to_the_default_and_says_so(monkeypatch, capsys, bad):
    """Chosen strategy: warn on stderr + use the documented default, never raise.
    See core/config.py's module docstring for why (statusline/hook re-execution)."""
    monkeypatch.setenv("TOKEN_FINOPS_WARN_AT", bad)
    assert config.thresholds() == (0.75, 0.90)
    err = capsys.readouterr().err
    assert "TOKEN_FINOPS_WARN_AT" in err and "ignoring" in err and bad in err


def test_an_invalid_env_var_falls_through_to_config_json_not_to_the_default(write_config, monkeypatch,
                                                                            capsys):
    """A broken setting must not promote itself past a working one: skipping the bad
    env value lands on the user's config.json, not on the hardcoded 0.75."""
    write_config({"budget": {"warn_at": 0.1, "critical_at": 0.25}})
    monkeypatch.setenv("TOKEN_FINOPS_WARN_AT", "1.5")
    assert config.thresholds() == (0.1, 0.25)
    assert "TOKEN_FINOPS_WARN_AT" in capsys.readouterr().err


def test_warn_at_above_critical_at_rejects_both_to_stay_coherent(write_config, capsys):
    """Both values are individually legal here; the *pair* is not, so both fall back
    rather than leaving a policy where WARN can never fire before CRITICAL."""
    write_config({"budget": {"warn_at": 0.95, "critical_at": 0.80}})
    assert config.thresholds() == (0.75, 0.90)
    assert "warn_at must be below critical_at" in capsys.readouterr().err


def test_equal_thresholds_are_rejected(write_config):
    write_config({"budget": {"warn_at": 0.9, "critical_at": 0.9}})
    assert config.thresholds() == (0.75, 0.90)


def test_a_bad_value_is_reported_once_not_once_per_adapter(monkeypatch, capsys):
    """`report` builds one policy per adapter; nine identical complaints is noise."""
    monkeypatch.setenv("TOKEN_FINOPS_CRITICAL_AT", "banana")
    for _ in range(5):
        config.thresholds()
    assert capsys.readouterr().err.count("TOKEN_FINOPS_CRITICAL_AT") == 1


def test_config_section_ignores_a_non_object_budget_key(write_config):
    write_config({"budget": "0.8"})
    assert config.thresholds() == (0.75, 0.90)


# --------------------------------------------------------------------------- #
# Thresholds reach BudgetPolicy -- without touching any of the 9 adapters
# --------------------------------------------------------------------------- #
def test_budget_policy_defaults_read_the_config(write_config):
    write_config({"budget": {"warn_at": 0.4, "critical_at": 0.5}})
    p = BudgetPolicy(tool="x", window_id="month", unit=Unit.AIU, cycle=CycleKind.CALENDAR_MONTH_UTC)
    assert (p.warn_at, p.critical_at) == (0.4, 0.5)


def test_explicit_constructor_values_still_win_over_the_config(write_config):
    write_config({"budget": {"warn_at": 0.4, "critical_at": 0.5}})
    p = BudgetPolicy(tool="x", window_id="month", unit=Unit.AIU, cycle=CycleKind.CALENDAR_MONTH_UTC,
                     warn_at=0.6, critical_at=0.7)
    assert (p.warn_at, p.critical_at) == (0.6, 0.7)


def test_every_adapter_policy_picks_the_config_up_with_no_adapter_change(write_config, home):
    """The point of resolving this in `BudgetPolicy`'s default factory: none of the
    nine `default_policy()` implementations mentions warn_at/critical_at, and none
    has to. If someone later hardcodes a threshold in an adapter, this fails."""
    write_config({"budget": {"warn_at": 0.11, "critical_at": 0.22}})
    adapters = all_adapters()
    assert len(adapters) >= 9
    for ad in adapters:
        p = ad.default_policy()
        assert (p.warn_at, p.critical_at) == (0.11, 0.22), f"{ad.tool} ignores the configured thresholds"


# --------------------------------------------------------------------------- #
# Thresholds actually change a tool's status
# --------------------------------------------------------------------------- #
def _late_month_runway(allowance=1000.0, used_aiu=800.0):
    """80 % of a monthly allowance, burned early, evaluated half a day before the
    reset -- so the pace rule ("projected to run out before reset") cannot fire and
    the status is decided purely by warn_at/critical_at."""
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    ev = make_event(days_ago=29.0, now=now, aiu=used_aiu)
    policy = BudgetPolicy(tool="copilot", window_id="month", unit=Unit.AIU,
                          cycle=CycleKind.CALENDAR_MONTH_UTC, allowance=allowance)
    return compute_runway([ev], policy, now=now)


def test_default_thresholds_put_80_percent_at_warn():
    rw = _late_month_runway()
    assert rw.used_fraction == pytest.approx(0.8)
    assert rw.runway_days > rw.days_left          # the pace rule is not what decides this
    assert rw.status is Status.WARN


def test_lower_thresholds_from_config_turn_the_same_usage_critical(write_config):
    write_config({"budget": {"warn_at": 0.5, "critical_at": 0.6}})
    assert _late_month_runway().status is Status.CRITICAL


def test_higher_thresholds_from_env_turn_the_same_usage_ok(monkeypatch):
    monkeypatch.setenv("TOKEN_FINOPS_WARN_AT", "0.85")
    monkeypatch.setenv("TOKEN_FINOPS_CRITICAL_AT", "0.95")
    assert _late_month_runway().status is Status.OK


# --------------------------------------------------------------------------- #
# Cycle day
# --------------------------------------------------------------------------- #
def test_cycle_day_precedence(write_config, monkeypatch):
    write_config({"budget": {"cycle_day": 12}})
    assert config.cycle_day() == 12
    monkeypatch.setenv("TOKEN_FINOPS_CYCLE_DAY", "20")
    assert config.cycle_day() == 20
    config.set_cli_overrides(cycle_day=7)          # what `--cycle-day 7` installs
    assert config.cycle_day() == 7


@pytest.mark.parametrize("bad", ["0", "31", "-1", "not-a-day", "15.5"])
def test_invalid_cycle_day_falls_back_to_the_first(monkeypatch, capsys, bad):
    """29-31 are rejected on purpose: `calendar_month_window()` would raise every
    February on a day that does not exist."""
    monkeypatch.setenv("TOKEN_FINOPS_CYCLE_DAY", bad)
    assert config.cycle_day() == 1
    assert "cycle_day" in capsys.readouterr().err


def test_configured_cycle_day_moves_the_copilot_reset(copilot_db, run_cli, write_config):
    write_config({"budget": {"cycle_day": 15}})
    assert json.loads(run_cli("report", "--json"))[0]["resets_at"].endswith("-15 00:00:00+00:00")


def test_explicit_cycle_day_flag_beats_the_config(copilot_db, run_cli, write_config):
    write_config({"budget": {"cycle_day": 15}})
    d = json.loads(run_cli("report", "--json", "--cycle-day", "20"))[0]
    assert d["resets_at"].endswith("-20 00:00:00+00:00")


# --------------------------------------------------------------------------- #
# Allowance
# --------------------------------------------------------------------------- #
def test_allowance_accepts_a_per_tool_map(write_config):
    write_config({"budget": {"allowance": {"copilot": 3000, "gemini_cli": 1000}}})
    assert config.allowance("copilot") == 3000.0
    assert config.allowance("gemini_cli") == 1000.0
    assert config.allowance("codex") is None


def test_allowance_accepts_a_single_number_for_every_tool(write_config):
    write_config({"budget": {"allowance": 500}})
    assert config.allowance("copilot") == config.allowance("codex") == 500.0


def test_allowance_env_vars_split_copilot_from_the_rest(write_config, monkeypatch):
    write_config({"budget": {"allowance": {"copilot": 3000, "codex": 10}}})
    monkeypatch.setenv("TOKEN_FINOPS_BUDGET", "1500")        # the `--budget` twin
    monkeypatch.setenv("TOKEN_FINOPS_ALLOWANCE", "42")       # the `--allowance` twin
    assert config.allowance("copilot") == 1500.0
    assert config.allowance("codex") == 42.0


@pytest.mark.parametrize("bad", ["0", "-5", "abc"])
def test_invalid_allowance_is_ignored(monkeypatch, capsys, bad):
    monkeypatch.setenv("TOKEN_FINOPS_BUDGET", bad)
    assert config.allowance("copilot") is None
    assert "allowance[copilot]" in capsys.readouterr().err


def test_configured_allowance_reaches_report(copilot_db, run_cli, write_config):
    write_config({"budget": {"allowance": {"copilot": 1200}}})
    assert json.loads(run_cli("report", "--json"))[0]["allowance"] == 1200.0


def test_budget_flag_beats_env_and_config(copilot_db, run_cli, write_config, monkeypatch):
    write_config({"budget": {"allowance": {"copilot": 1200}}})
    monkeypatch.setenv("TOKEN_FINOPS_BUDGET", "1300")
    assert json.loads(run_cli("report", "--json"))[0]["allowance"] == 1300.0
    assert json.loads(run_cli("report", "--json", "--budget", "1400"))[0]["allowance"] == 1400.0


def test_cli_overrides_do_not_leak_between_runs(copilot_db, run_cli):
    """`main()` reinstalls the CLI tier on every invocation, so the in-process test
    runner (and `report --watch`) cannot carry a flag into the next command."""
    assert json.loads(run_cli("report", "--json", "--budget", "1400"))[0]["allowance"] == 1400.0
    assert json.loads(run_cli("report", "--json"))[0]["allowance"] == 20_000.0   # DEFAULT_BUDGET_AIU


# --------------------------------------------------------------------------- #
# Rolling window length -- and the rule that real data outranks it
# --------------------------------------------------------------------------- #
def test_window_hours_config_shapes_a_rolling_policy(write_config):
    write_config({"budget": {"window_hours": {"claude_code:5h": 26}}})
    p = BudgetPolicy(tool="claude_code", window_id="5h", unit=Unit.PERCENT,
                     cycle=CycleKind.ROLLING, window_length=timedelta(hours=5))
    assert p.window_length == timedelta(hours=26)


def test_window_hours_prefers_the_exact_tool_window_key(write_config):
    write_config({"budget": {"window_hours": {"claude_code": 9, "claude_code:7d": 200}}})
    five = BudgetPolicy(tool="claude_code", window_id="5h", unit=Unit.PERCENT,
                        cycle=CycleKind.ROLLING, window_length=timedelta(hours=5))
    seven = BudgetPolicy(tool="claude_code", window_id="7d", unit=Unit.PERCENT,
                         cycle=CycleKind.ROLLING, window_length=timedelta(days=7))
    assert five.window_length == timedelta(hours=9)      # falls back to the whole-tool entry
    assert seven.window_length == timedelta(hours=200)   # exact key wins


def test_window_hours_env_accepts_a_bare_number_and_a_key_list(monkeypatch):
    def length(tool, window):
        return BudgetPolicy(tool=tool, window_id=window, unit=Unit.PERCENT, cycle=CycleKind.ROLLING,
                            window_length=timedelta(hours=5)).window_length

    monkeypatch.setenv("TOKEN_FINOPS_WINDOW_HOURS", "8")
    assert length("claude_code", "5h") == length("codex", "5h") == timedelta(hours=8)
    monkeypatch.setenv("TOKEN_FINOPS_WINDOW_HOURS", "claude_code:5h=26,codex=30")
    assert length("claude_code", "5h") == timedelta(hours=26)
    assert length("codex", "5h") == timedelta(hours=30)
    assert length("gemini_cli", "5h") == timedelta(hours=5)   # unmentioned tool keeps its own


def test_window_hours_is_ignored_for_non_rolling_cycles(write_config):
    write_config({"budget": {"window_hours": 99}})
    p = BudgetPolicy(tool="copilot", window_id="month", unit=Unit.AIU,
                     cycle=CycleKind.CALENDAR_MONTH_UTC)
    assert p.window_length is None


@pytest.mark.parametrize("bad", ["0", "-3", "zzz"])
def test_invalid_window_hours_keeps_the_adapter_default(monkeypatch, capsys, bad):
    monkeypatch.setenv("TOKEN_FINOPS_WINDOW_HOURS", bad)
    assert config.window_length("claude_code", "5h", timedelta(hours=5)) == timedelta(hours=5)
    assert "window_hours" in capsys.readouterr().err


def _quota_file(home, used_pct: float, resets_at: datetime) -> None:
    d = home / ".token-finops"
    d.mkdir(parents=True, exist_ok=True)
    (d / "quota.json").write_text(json.dumps({
        "observed_at": (REAL_NOW - timedelta(minutes=1)).isoformat(),
        "rate_limits": {"five_hour": {"used_percentage": used_pct,
                                      "resets_at": resets_at.isoformat()}},
    }), encoding="utf-8")


def test_configured_window_never_moves_a_real_resets_at(home, run_cli, write_config):
    """`resets_at` is data Claude Code itself recorded. A configured window length is
    only a guess at the window's *span*, which no provider reports -- it may shape the
    elapsed/pace figures, but it must never rewrite a reset time we actually know."""
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    resets = (REAL_NOW + timedelta(hours=2)).replace(microsecond=0)
    _quota_file(home, 40.0, resets)
    write_config({"budget": {"window_hours": {"claude_code:5h": 26}}})
    d = json.loads(run_cli("report", "--json", "--tool", "claude_code"))[0]
    assert d["resets_at"].startswith(resets.isoformat(sep=" ")[:16])
    assert d["used_fraction"] == pytest.approx(0.4)


def test_claude_code_status_follows_the_configured_thresholds(home, run_cli, write_config):
    """End to end on the percent path: one snapshot, no history, so there is no burn
    estimate and the status word comes straight from warn_at/critical_at."""
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    _quota_file(home, 80.0, (REAL_NOW + timedelta(hours=2)).replace(microsecond=0))

    def status():
        return json.loads(run_cli("report", "--json", "--tool", "claude_code"))[0]["status"]

    assert status() == "WARN"                                  # defaults 0.75 / 0.90
    write_config({"budget": {"warn_at": 0.5, "critical_at": 0.6}})
    assert status() == "CRITICAL"
    write_config({"budget": {"warn_at": 0.85, "critical_at": 0.95}})
    assert status() == "OK"


# --------------------------------------------------------------------------- #
# default_tool ("default agent")
# --------------------------------------------------------------------------- #
def test_default_tool_from_config_and_env(write_config, monkeypatch):
    write_config({"default_tool": "copilot"})
    assert config.default_tool(valid={"copilot", "claude_code"}) == "copilot"
    monkeypatch.setenv("TOKEN_FINOPS_DEFAULT_TOOL", "claude_code")
    assert config.default_tool(valid={"copilot", "claude_code"}) == "claude_code"


def test_unknown_default_tool_is_ignored_with_a_warning(write_config, capsys):
    write_config({"default_tool": "emacs-doctor"})
    assert config.default_tool(valid={"copilot", "claude_code"}) is None
    err = capsys.readouterr().err
    assert "emacs-doctor" in err and "no such tool" in err


def test_non_string_default_tool_is_ignored(write_config, capsys):
    write_config({"default_tool": ["copilot"]})
    assert config.default_tool(valid={"copilot"}) is None
    assert "must be a string" in capsys.readouterr().err


def test_default_tool_restricts_report_to_that_tool(copilot_db, home, run_cli, write_config):
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    assert {d["tool"] for d in json.loads(run_cli("report", "--json"))} == {"copilot", "claude_code"}
    write_config({"default_tool": "claude_code"})
    assert {d["tool"] for d in json.loads(run_cli("report", "--json"))} == {"claude_code"}


def test_explicit_tool_flag_always_beats_the_configured_default(copilot_db, home, run_cli, write_config):
    build_claude_tree(home / ".claude", REAL_NOW - timedelta(hours=1))
    write_config({"default_tool": "claude_code"})
    assert {d["tool"] for d in json.loads(run_cli("report", "--json", "--tool", "copilot"))} == {"copilot"}


def test_default_tool_applies_to_every_subcommand_that_takes_tool(home, monkeypatch):
    """Not just `report`: whatever subcommand exposes `--tool` gets the same default,
    which is the whole point of resolving it once in `main()`."""
    all_adapters()
    monkeypatch.setenv("TOKEN_FINOPS_DEFAULT_TOOL", "codex")
    parser = cli.build_parser()
    for argv in (["report"], ["sessions"], ["doctor"], ["status"], ["burn"],
                 ["cost-per-token"], ["break-even"]):
        args = parser.parse_args(argv)
        cli.apply_config_defaults(args)
        assert args.tool == ["codex"], argv


def test_an_unknown_configured_default_tool_still_reports_everything(copilot_db, run_cli, write_config):
    """Degrade gracefully: a typo must not silently produce an empty report."""
    write_config({"default_tool": "copilto"})
    assert json.loads(run_cli("report", "--json"))[0]["tool"] == "copilot"


# --------------------------------------------------------------------------- #
# The --budget/--allowance/--cycle-day flags are accepted everywhere now
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("command", ["report", "sessions", "doctor", "status", "burn", "cost-per-token"])
def test_budget_overrides_are_accepted_by_every_telemetry_subcommand(home, command):
    """`token-finops burn --budget 1500` used to die with "unrecognized arguments"."""
    all_adapters()
    args = cli.build_parser().parse_args([command, "--budget", "1500", "--allowance", "7",
                                          "--cycle-day", "9"])
    assert (args.budget, args.allowance, args.cycle_day) == (1500.0, 7.0, 9)
    cli.apply_config_defaults(args)
    assert config.allowance("copilot") == 1500.0
    assert config.allowance("codex") == 7.0
    assert config.cycle_day() == 9


def test_doctor_shows_the_effective_settings(home, run_cli, write_config):
    write_config({"budget": {"warn_at": 0.6, "critical_at": 0.7, "cycle_day": 9},
                  "default_tool": "codex"})
    out = run_cli("doctor")
    assert "thresholds: WARN at 60% of the window, CRITICAL at 70%" in out
    assert "cycle day:  9" in out
    assert "default tool: codex" in out


# --------------------------------------------------------------------------- #
# Backward compatibility with the original statusline-only config
# --------------------------------------------------------------------------- #
def test_the_original_statusline_shape_still_parses(write_config):
    """`{"statusline": {"show_subagents": true}}` was the only thing this file held
    before it became the shared settings file; it must keep working verbatim."""
    write_config({"statusline": {"show_subagents": True}})
    assert cli._statusline_config().get("statusline", {}).get("show_subagents") is True
    assert config.section("statusline") == {"show_subagents": True}


def test_statusline_and_budget_settings_coexist_in_one_file(write_config):
    write_config({"statusline": {"show_subagents": True},
                  "budget": {"warn_at": 0.5, "critical_at": 0.6},
                  "default_tool": "copilot"})
    assert cli._statusline_config()["statusline"]["show_subagents"] is True
    assert config.thresholds() == (0.5, 0.6)
    assert config.default_tool(valid={"copilot"}) == "copilot"


def test_statusline_colour_follows_the_configured_thresholds(write_config):
    """The status-bar colour and `report`'s status word must never disagree."""
    assert cli._pct_colour(80.0) == cli._ANSI_WARN
    write_config({"budget": {"warn_at": 0.3, "critical_at": 0.5}})
    assert cli._pct_colour(80.0) == cli._ANSI_CRITICAL
    assert cli._pct_colour(40.0) == cli._ANSI_WARN
    assert cli._pct_colour(10.0) == cli._ANSI_OK


def test_config_at_the_default_home_location_is_found(home, run_cli, monkeypatch):
    """Not only via $TOKEN_FINOPS_CONFIG: the documented `~/.token-finops/config.json`
    is what users actually create."""
    db = home / "c.db"
    write_copilot_db(db, [{"ts": REAL_NOW - timedelta(minutes=5), "nano_aiu": 100 * 10**9}])
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    d = home / ".token-finops"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"budget": {"allowance": {"copilot": 777}}}),
                                   encoding="utf-8")
    assert json.loads(run_cli("report", "--json"))[0]["allowance"] == 777.0
