"""Tests for `token_finops_cli.burn.history` (daily aggregates, upsert/read of the history
file, period grouping) and for the `token-finops burn` CLI end-to-end on a synthetic home."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from token_finops_cli.burn import history as hist
from token_finops_cli.cli import _normalize_argv
from token_finops_cli.synth import generate
from token_finops_cli.synth.env import env_for

from conftest import NOW, make_event


# --------------------------------------------------------------------------- #
# daily aggregates / merge
# --------------------------------------------------------------------------- #
def test_daily_aggregates_groups_by_utc_day():
    berlin = timezone(timedelta(hours=2))
    evs = [
        make_event(0, now=datetime(2026, 9, 10, 23, 30, tzinfo=timezone.utc), tool="claude_code",
                   model="claude-sonnet-5", usd=1.0, inp=10, out=20, cr=30, cw=40),
        # 01:30 Berlin on the 11th is still 23:30 UTC on the 10th
        make_event(0, now=datetime(2026, 9, 11, 1, 30, tzinfo=berlin), tool="claude_code",
                   model="claude-haiku-4-5", usd=0.5, inp=1, out=2, cr=3, cw=4),
        make_event(0, now=datetime(2026, 9, 11, 0, 30, tzinfo=timezone.utc), tool="claude_code",
                   model="claude-sonnet-5", usd=None, inp=100, out=200),
    ]
    days = hist.daily_aggregates(evs, "claude_code")
    assert set(days) == {"2026-09-10", "2026-09-11"}
    d10 = days["2026-09-10"]
    assert d10["schema_version"] == hist.SCHEMA_VERSION and d10["tool"] == "claude_code"
    assert (d10["calls"], d10["input"], d10["output"], d10["cache_read"], d10["cache_write"]) == (2, 11, 22, 33, 44)
    assert d10["usd"] == pytest.approx(1.5)
    assert d10["by_model"] == {"claude-sonnet-5": 1.0, "claude-haiku-4-5": 0.5}
    d11 = days["2026-09-11"]
    assert d11["calls"] == 1 and d11["usd"] == 0.0 and d11["by_model"] == {}  # usd None counted, not priced
    assert hist.daily_aggregates([], "x") == {}


def _rec(day="2026-09-10", tool="claude_code", **over):
    base = {"schema_version": 1, "tool": tool, "day": day, "calls": 1, "input": 1, "output": 1,
            "cache_read": 1, "cache_write": 1, "usd": 1.0, "by_model": {"m": 1.0}}
    base.update(over)
    return base


def test_upsert_is_idempotent_and_latest_wins(tmp_path):
    path = tmp_path / "deep" / "history.jsonl"  # parent dir is created on demand
    t1 = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)
    assert hist.upsert([_rec(calls=1, usd=1.0)], str(path), now=t1) == 1
    assert hist.upsert([_rec(calls=5, usd=9.0)], str(path), now=t1 + timedelta(hours=1)) == 1
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["calls"] == 5 and rec["usd"] == 9.0
    assert rec["recorded_at"] == "2026-09-10T11:00:00+00:00"
    # a different (tool, day) adds a line; output is sorted by (tool, day)
    assert hist.upsert([_rec(day="2026-09-01", tool="codex")], str(path)) == 2
    rows = hist.read_history(str(path))
    assert [(r["tool"], r["day"]) for r in rows] == [("claude_code", "2026-09-10"), ("codex", "2026-09-01")]
    assert not (tmp_path / "deep" / "history.jsonl.tmp").exists()


def test_read_history_skips_corrupt_and_wrong_schema(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text("\n".join([
        json.dumps(_rec()),
        "not json",
        "",
        json.dumps(_rec(day="2026-09-11", schema_version=2)),
        json.dumps({"schema_version": 1, "tool": "x"}),  # no day
        json.dumps(["schema_version", 1]),
        json.dumps(_rec(day="2026-09-12")),
    ]) + "\n")
    rows = hist.read_history(str(path))
    assert [r["day"] for r in rows] == ["2026-09-10", "2026-09-12"]
    assert hist.read_history(str(tmp_path / "missing.jsonl")) == []


def test_merge_live_wins_and_history_fills_gaps():
    live = {"2026-09-10": {"day": "2026-09-10", "calls": 7, "usd": 7.0}}
    history = [_rec(day="2026-09-10", calls=1, usd=1.0), _rec(day="2026-09-01", calls=2, usd=2.0),
               _rec(day="2026-09-02", tool="codex", calls=3)]
    merged = hist.merge_live(live, history, "claude_code")
    assert set(merged) == {"2026-09-01", "2026-09-10"}
    assert merged["2026-09-10"]["calls"] == 7  # live wins
    assert merged["2026-09-01"]["calls"] == 2  # history fills
    assert hist.merge_live({}, [], "claude_code") == {}


# --------------------------------------------------------------------------- #
# periods
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("day, by, key", [
    ("2026-09-11", "day", "2026-09-11"),
    ("2026-09-11", "week", "2026-W37"),
    ("2026-09-11", "month", "2026-09"),
    ("2026-12-31", "week", "2026-W53"),  # 2026-12-31 is a Thursday -> ISO year 2026 has 53 weeks
    ("2027-01-01", "week", "2026-W53"),  # ... and New Year's Day still belongs to it
    ("2027-01-04", "week", "2027-W01"),
    ("2027-01-01", "month", "2027-01"),
    ("2026-01-04", "week", "2026-W01"),  # 2026-01-04 is a Sunday -> last day of week 1
])
def test_period_key(day, by, key):
    assert hist.period_key(day, by) == key


def test_period_key_rejects_unknown_granularity():
    with pytest.raises(ValueError):
        hist.period_key("2026-09-11", "quarter")


@pytest.mark.parametrize("key, by, days", [
    ("2028-02", "month", 29), ("2026-02", "month", 28), ("2026-12", "month", 31), ("2026-09", "month", 30),
    ("2026-W37", "week", 7), ("2026-09-11", "day", 1),
])
def test_period_days(key, by, days):
    assert hist.period_days(key, by) == days


def test_group_sums_fields_and_sorts_keys():
    days = {"2026-09-11": _rec(day="2026-09-11", calls=2, usd=2.0, by_model={"a": 2.0}),
            "2026-09-01": _rec(day="2026-09-01", calls=3, usd=3.0, by_model={"a": 1.0, "b": 2.0}),
            "2026-08-31": _rec(day="2026-08-31", calls=4, usd=4.0)}
    g = hist.group(days, "month")
    assert list(g) == ["2026-08", "2026-09"]
    sep = g["2026-09"]
    assert sep["days"] == 2 and sep["calls"] == 5 and sep["usd"] == pytest.approx(5.0)
    assert sep["by_model"] == {"a": 3.0, "b": 2.0} and isinstance(sep["by_model"], dict)
    assert sep["tokens"] == 8  # 4 token fields of 1 each over 2 days
    wk = hist.group(days, "week")
    assert list(wk) == ["2026-W36", "2026-W37"]  # 2026-08-31 (Mon) and 2026-09-01 share week 36
    assert wk["2026-W36"]["days"] == 2


# --------------------------------------------------------------------------- #
# partial periods (run-rate normalisation by actually-observed days, not calendar length)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key, by, first_day, last_day, expected_days, expected_partial", [
    # window fully covers the calendar week -> unclipped, not partial
    ("2026-W37", "week", "2026-09-07", "2026-09-13", 7, False),
    # window starts mid-week -> only the tail of the week is observed
    ("2026-W37", "week", "2026-09-11", "2026-09-20", 3, True),  # Fri..Sun of that week = 3 days
    # window ends mid-week -> only the head of the week is observed
    ("2026-W37", "week", "2026-09-01", "2026-09-09", 3, True),  # Mon..Wed = 3 days
    # window fully covers the calendar month -> unclipped
    ("2026-09", "month", "2026-09-01", "2026-09-30", 30, False),
    ("2026-09", "month", "2026-08-01", "2026-10-31", 30, False),  # window wider than the month
    # window covers only part of the month at each edge
    ("2026-09", "month", "2026-09-20", "2026-10-05", 11, True),  # Sep 20..30
    ("2026-09", "month", "2026-08-25", "2026-09-05", 5, True),   # Sep 1..5
    ("2026-09-11", "day", "2026-09-11", "2026-09-11", 1, False),
])
def test_period_window_days(key, by, first_day, last_day, expected_days, expected_partial):
    days, partial = hist.period_window_days(key, by, first_day, last_day)
    assert (days, partial) == (expected_days, expected_partial)


def test_period_bounds():
    assert hist.period_bounds("2026-09-11", "day") == (date(2026, 9, 11), date(2026, 9, 11))
    assert hist.period_bounds("2026-W37", "week") == (date(2026, 9, 7), date(2026, 9, 13))
    assert hist.period_bounds("2026-09", "month") == (date(2026, 9, 1), date(2026, 9, 30))
    assert hist.period_bounds("2026-02", "month") == (date(2026, 2, 1), date(2026, 2, 28))


def test_group_week_with_only_three_of_seven_days_normalises_by_three():
    """Only Fri/Sat/Sun (3 of the 7 calendar days of that ISO week) have events -> the group's
    period_days must be 3, not the calendar 7, so a run-rate divided by it isn't understated."""
    days = {"2026-09-11": _rec(day="2026-09-11", calls=1, usd=3.0),   # Friday, week 37
            "2026-09-12": _rec(day="2026-09-12", calls=1, usd=3.0),   # Saturday
            "2026-09-13": _rec(day="2026-09-13", calls=1, usd=3.0)}   # Sunday
    g = hist.group(days, "week")
    assert list(g) == ["2026-W37"]
    wk = g["2026-W37"]
    assert wk["days"] == 3  # days with data
    assert wk["period_days"] == 3  # normalisation denominator: actually observed, not 7
    assert wk["partial"] is True
    usd_per_30d = wk["usd"] * 30.0 / wk["period_days"]
    assert usd_per_30d == pytest.approx(9.0 * 30 / 3)
    assert usd_per_30d != pytest.approx(9.0 * 30 / 7)  # the bug being fixed: NOT the calendar length


def test_group_full_week_normalises_by_seven_and_is_not_partial():
    days = {f"2026-09-{d:02d}": _rec(day=f"2026-09-{d:02d}", calls=1, usd=1.0) for d in range(7, 14)}
    g = hist.group(days, "week")
    wk = g["2026-W37"]
    assert wk["days"] == 7 and wk["period_days"] == 7 and wk["partial"] is False


def test_group_full_month_normalises_by_calendar_days_in_that_month():
    days = {f"2026-09-{d:02d}": _rec(day=f"2026-09-{d:02d}", calls=1, usd=1.0) for d in range(1, 31)}
    g = hist.group(days, "month")
    mo = g["2026-09"]
    assert mo["days"] == 30 and mo["period_days"] == 30 and mo["partial"] is False
    # a different, shorter month: February 2026 has 28 days
    feb = {f"2026-02-{d:02d}": _rec(day=f"2026-02-{d:02d}", calls=1, usd=1.0) for d in range(1, 29)}
    gf = hist.group(feb, "month")
    assert gf["2026-02"]["period_days"] == 28 and gf["2026-02"]["partial"] is False


def test_group_empty_days_has_no_periods():
    assert hist.group({}, "month") == {}


def test_cutoff_day():
    assert hist.cutoff_day(None) is None
    assert hist.cutoff_day(timedelta(days=30), now=NOW) == "2026-08-16"
    assert hist.cutoff_day(timedelta(days=0), now=NOW) == "2026-09-15"
    assert hist.cutoff_day(timedelta(days=1)) is not None


# --------------------------------------------------------------------------- #
# CLI on a synthetic home
# --------------------------------------------------------------------------- #
def _synth_home(tmp_path, monkeypatch, now=None):
    out = tmp_path / "home"
    generate(str(out), tools=["claude_code"], days=14, seed=7, now=now)
    for var, val in env_for(str(out)).items():
        monkeypatch.setenv(var, val)
    from token_finops_cli.adapters import claude_code
    from token_finops_cli.core import pricing
    monkeypatch.setattr(claude_code, "QUOTA_FILE", str(out / ".token-finops" / "quota.json"))
    monkeypatch.setattr(claude_code, "QUOTA_HISTORY_FILE", str(out / ".token-finops" / "quota_history.jsonl"))
    monkeypatch.setattr(pricing, "_TABLE", None)
    return out


def test_normalize_argv_treats_burn_as_command():
    assert _normalize_argv(["burn", "--plans"]) == ["burn", "--plans"]
    assert _normalize_argv(["--since", "7d"]) == ["report", "--since", "7d"]
    assert _normalize_argv([]) == ["report"]


def test_cli_plans_lists_catalogue(home, run_cli):
    out = run_cli("burn", "--plans")
    assert out.startswith("Plan catalogue")
    assert "claude:max-20x" in out and "Claude Max 20x" in out and "200.00/mo" in out
    assert "Burn report" not in out


def test_cli_json_report_has_all_sections(tmp_path, monkeypatch, run_cli):
    _synth_home(tmp_path, monkeypatch)
    out = run_cli("burn", "--since", "all", "--tool", "claude_code", "--plan", "claude:max-20x", "--by", "week",
                  "--efficiency", "--rate", "3/15", "--discount", "0.5", "--json")
    data = json.loads(out)
    assert data["history_lines"] is None
    assert len(data["reports"]) == 1
    r = data["reports"][0]
    assert r["tool"] == "claude_code" and r["label"] == "all time" and r["by"] == "week"
    for key in ("plans", "periods", "efficiency", "prepaid", "discount"):
        assert r[key], key
    assert {p["id"] for p in r["plans"]} == {"claude:pro", "claude:max-5x", "claude:max-20x", "claude:team"}
    assert r["my_plan"]["id"] == "claude:max-20x"
    assert r["discount"]["factor"] == 0.5 and r["discount"]["usd"] == pytest.approx(r["usd"] * 0.5)
    assert r["prepaid"]["rate"] == {"input": 3.0, "output": 15.0, "cache_read": pytest.approx(0.3),
                                    "cache_write": pytest.approx(3.75)}
    assert r["prepaid"]["usd"] > 0
    assert all(g["period"][4:6] == "-W" for g in r["periods"])
    assert sum(g["calls"] for g in r["periods"]) == r["efficiency"]["calls"] == 84
    assert 0 < r["efficiency"]["cache_hit"] < 1
    assert r["efficiency"]["subagent_share"] > 0  # synthetic tree has sub-agents


def test_cli_text_report_on_synthetic_home(tmp_path, monkeypatch, run_cli):
    _synth_home(tmp_path, monkeypatch)
    out = run_cli("burn", "--since", "all", "--tool", "claude_code", "--plan", "claude:max-20x", "--by", "month",
                  "--efficiency", "--discount", "0.25")
    assert "Burn report: Claude Code (all time)" in out
    assert "<- yours" in out and "with 25% discount:" in out and "prepaid" not in out
    assert "By month:" in out and "Burn efficiency:" in out and "Maxing scale:" in out
    assert "history:" not in out


def test_cli_discount_out_of_range_is_an_error_string(home, run_cli):
    assert run_cli("burn", "--discount", "1.5").strip() == "--discount must be a fraction in [0, 1), e.g. 0.5"
    assert run_cli("burn", "--discount", "-0.1").strip().startswith("--discount must be")


def test_cli_no_data_message(home, run_cli):
    assert run_cli("burn", "--tool", "claude_code").startswith("No usage events found")


def test_cli_record_then_history(tmp_path, monkeypatch, run_cli):
    _synth_home(tmp_path, monkeypatch)
    hfile = tmp_path / "hist" / "history.jsonl"
    out = run_cli("burn", "--since", "all", "--tool", "claude_code", "--record", "--history-file", str(hfile))
    assert f"history: 14 tool-day lines in {hfile}" in out
    rows = hist.read_history(str(hfile))
    assert len(rows) == 14 and {r["tool"] for r in rows} == {"claude_code"}
    assert all(r["recorded_at"] for r in rows)
    # recording again is idempotent
    run_cli("burn", "--since", "all", "--tool", "claude_code", "--record", "--history-file", str(hfile))
    assert len(hfile.read_text().splitlines()) == 14

    # an old day the tool itself has long forgotten
    old = _rec(day="2025-03-05", calls=11, input=100, output=200, cache_read=300, cache_write=400, usd=12.5,
               by_model={"claude-sonnet-5": 12.5})
    hist.upsert([old], str(hfile))
    out = run_cli("burn", "--since", "all", "--tool", "claude_code", "--history", "--history-file", str(hfile),
                  "--by", "month")
    assert "By month (live telemetry + recorded history):" in out
    row = next(ln for ln in out.splitlines() if ln.strip().startswith("2025-03"))
    assert row.split()[1:5] == ["1", "11", "1.0k", "12.50"]
    # JSON path carries the same period
    data = json.loads(run_cli("burn", "--since", "all", "--tool", "claude_code", "--history", "--history-file",
                              str(hfile), "--by", "month", "--json"))
    months = {g["period"]: g for g in data["reports"][0]["periods"]}
    assert months["2025-03"]["usd"] == pytest.approx(12.5)
    assert data["reports"][0]["with_history"] is True
    # without --history the old month is invisible
    assert "2025-03" not in run_cli("burn", "--since", "all", "--tool", "claude_code", "--by", "month",
                                    "--history-file", str(hfile))


def test_cli_history_only_window(tmp_path, monkeypatch, run_cli):
    """`--since 1d` filters every live event out (the synthetic tree ends three days ago), but a
    recorded line for today keeps the tool in the report with a By-month table."""
    now = datetime.now(timezone.utc)
    _synth_home(tmp_path, monkeypatch, now=now - timedelta(days=3))
    hfile = tmp_path / "history.jsonl"
    today = now.date().isoformat()
    hist.upsert([_rec(day=today, calls=5, usd=4.0, by_model={"claude-sonnet-5": 4.0})], str(hfile))
    argv = ("burn", "--since", "1d", "--tool", "claude_code", "--history", "--history-file", str(hfile),
            "--by", "month")
    data = json.loads(run_cli(*argv, "--json"))
    r = data["reports"][0]
    assert r["efficiency"]["calls"] == 0 and r["with_history"] is True
    assert [g["period"] for g in r["periods"]] == [today[:7]]
    assert r["periods"][0]["calls"] == 5
    out = run_cli(*argv)
    assert "Burn report: Claude Code" in out
    assert today[:7] in out and "By month" in out
    # ... whereas without history the window is simply empty
    assert run_cli("burn", "--since", "1d", "--tool", "claude_code").startswith("No usage events found")
