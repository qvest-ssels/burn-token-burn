"""report.py: number formatting, progress bars, runway/compact rendering and
the usage summaries. All output must stay plain ASCII."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

import pytest
from conftest import NOW, make_event, month_policy, percent_policy

from token_finops_cli.core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Runway, Status, Unit
from token_finops_cli.core.runway import compute_runway
from token_finops_cli.report import (by_model, compact_line, fmt_amount, fmt_days, fmt_dt, fmt_tokens, fmt_usd,
                                     progress_bar, render_by_model, render_runway, render_sessions_table,
                                     render_summary, summarize, unit_label)


# --------------------------------------------------------------------------- #
# formatters
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("n, s", [
    (0, "0"), (999, "999"), (999.9, "999"), (1000, "1.0k"), (1500, "1.5k"), (999_949, "999.9k"),
    (999_999, "1000.0k"), (1_000_000, "1.0M"), (2_500_000, "2.5M"), (999_999_999, "1000.0M"),
    (1_000_000_000, "1.00B"), (12_345_678_901, "12.35B"), (-5, "-5"),
])
def test_fmt_tokens(n, s):
    assert fmt_tokens(n) == s


def test_fmt_usd():
    assert fmt_usd(None) == "n/a"
    assert fmt_usd(0) == "$0.00"
    assert fmt_usd(1234.567) == "$1,234.57"
    assert fmt_usd(0.004) == "$0.00"


@pytest.mark.parametrize("d, s", [
    (None, "n/a"), (math.inf, "inf"), (0.0, "0.0h"), (0.5, "12.0h"), (0.99, "23.8h"), (1.0, "1.0d"),
    (1.25, "1.2d"), (30.0, "30.0d"),
])
def test_fmt_days(d, s):
    assert fmt_days(d) == s


def test_progress_bar_none_and_clamping():
    assert progress_bar(None) == "[" + "?" * 30 + "]   n/a"
    assert progress_bar(None, width=4) == "[????]   n/a"
    assert progress_bar(0.0) == "[" + "-" * 30 + "]   0.0%"
    assert progress_bar(1.0) == "[" + "#" * 30 + "] 100.0%"
    assert progress_bar(1.7) == progress_bar(1.0)
    assert progress_bar(-0.3) == progress_bar(0.0)
    assert progress_bar(0.5, width=10) == "[#####-----]  50.0%"
    assert progress_bar(0.333, width=3) == "[#--]  33.3%"


def test_progress_bar_is_ascii_only():
    for f in (None, 0.0, 0.42, 1.0):
        assert progress_bar(f).isascii()


def test_unit_label_and_fmt_amount():
    assert {unit_label(u) for u in Unit} == {"AI units", "USD", "requests", "%", "tokens", "min"}
    assert fmt_amount(1234.5, Unit.USD) == "$1,234.50"
    assert fmt_amount(0.456, Unit.PERCENT) == "46%"
    assert fmt_amount(2_500_000, Unit.TOKENS) == "2.5M"
    assert fmt_amount(1234.56, Unit.AIU) == "1,234.6"
    assert fmt_amount(3, Unit.REQUESTS) == "3.0"
    assert fmt_amount(7.25, Unit.MINUTES) == "7.2"


def test_fmt_dt():
    assert fmt_dt(None) == "n/a"
    assert fmt_dt(NOW) == "2026-09-15 12:00 UTC"


# --------------------------------------------------------------------------- #
# render_runway
# --------------------------------------------------------------------------- #
def _percent_pct_pattern(text: str):
    """Any '%' immediately followed (after optional space) by another '%' is a rendering bug."""
    return re.search(r"%\s*%", text)


def test_render_runway_aiu_with_allowance():
    evs = [make_event(d, aiu=100.0) for d in range(10)]
    r = compute_runway(evs, month_policy(3000.0), now=NOW)
    lines = render_runway(r, "GitHub Copilot CLI")
    text = "\n".join(lines)
    assert lines[0] == "GitHub Copilot CLI — window: month (resets 2026-10-01 00:00 UTC)"
    assert "  used:     1,000.0 / 3,000.0 AI units" in lines
    assert lines[1].startswith("  budget:   [")
    assert any(ln.startswith("  window:   [") and ln.endswith("elapsed") for ln in lines)
    assert "  pace:     " in text and "(on pace)" in text
    burn = next(ln for ln in lines if ln.startswith("  burn:"))
    assert "AI units/day avg, EMA " in burn
    runway = next(ln for ln in lines if ln.startswith("  runway:"))
    assert runway.endswith(f"vs {fmt_days(r.days_left)} left -> OK")
    assert not any(ln.startswith("  note:") for ln in lines)
    assert text.replace("—", "").isascii()


def test_render_runway_too_fast_and_notes():
    r = Runway(tool="t", window_id="month", unit=Unit.AIU, now=NOW, window_start=NOW, resets_at=None,
               used=10.0, allowance=100.0, used_fraction=0.1, time_fraction=0.05, pace_ratio=2.0,
               burn_per_day_avg=5.0, burn_per_day_ema=None, runway_days=3.0, days_left=None,
               projected_exhaustion=None, status=Status.OK, notes=["hello", "world"])
    lines = render_runway(r, "X")
    assert lines[0] == "X — window: month (rolling)"
    assert "  pace:     2.00 (2.00x too fast)" in lines
    assert "  burn:     5.0 AI units/day avg" in lines          # no EMA suffix when None
    assert "  runway:   3.0d -> OK" in lines                    # no "vs ... left" without a reset
    assert lines[-2:] == ["  note:     hello", "  note:     world"]


def test_render_runway_without_allowance():
    r = compute_runway([make_event(1, aiu=42.0)], month_policy(None), now=NOW)
    lines = render_runway(r, "X")
    assert "  used:     42.0 AI units (no allowance set)" in lines
    assert "  runway:   n/a -> UNLIMITED" in lines
    assert lines[1] == "  budget:   " + progress_bar(None)


def test_render_runway_usd_unit():
    p = BudgetPolicy("openrouter", "30d", Unit.USD, CycleKind.SLIDING_FROM_FIRST_USE, allowance=50.0)
    evs = [make_event(1, aiu=1.25, native_unit=Unit.USD), make_event(2, aiu=None, usd=0.75)]
    r = compute_runway(evs, p, now=NOW)
    lines = render_runway(r, "OpenRouter")
    assert "  used:     $2.00 / $50.00 USD" in lines
    burn = next(ln for ln in lines if ln.startswith("  burn:"))
    assert burn.startswith("  burn:     $") and "USD/day avg" in burn


def test_render_runway_percent_unit_has_no_duplicate_percent_signs():
    q = QuotaSnapshot("claude_code", "5h", NOW, used_fraction=0.42, resets_at=NOW + timedelta(hours=2),
                      source="claude_statusline")
    hist = [QuotaSnapshot("claude_code", "5h", NOW - timedelta(hours=1), used_fraction=0.30,
                          resets_at=q.resets_at), q]
    r = compute_runway([], percent_policy(), now=NOW, quota=q, quota_history=hist)
    lines = render_runway(r, "Claude Code")
    text = "\n".join(lines)
    assert "  used:     42% of the 5h window" in lines
    assert "  burn:     12.0% per hour (from snapshots)" in lines
    assert not _percent_pct_pattern(text)
    assert "AI units" not in text and "%/day" not in text
    runway = next(ln for ln in lines if ln.startswith("  runway:"))
    assert "vs 2.0h left -> " in runway


def test_render_runway_percent_unknown():
    r = compute_runway([], percent_policy(), now=NOW)
    lines = render_runway(r, "Claude Code")
    assert lines[0] == "Claude Code — window: 5h (rolling)"
    assert not any(ln.startswith("  used:") for ln in lines)     # fraction unknown -> no used line
    assert "  runway:   n/a -> UNKNOWN" in lines
    assert any("collect-statusline" in ln for ln in lines if ln.startswith("  note:"))


def test_render_runway_tokens_unit_uses_token_formatting():
    p = BudgetPolicy("codex", "5h", Unit.TOKENS, CycleKind.ROLLING, allowance=2_000_000,
                     window_length=timedelta(hours=5))
    r = compute_runway([make_event(0.01, inp=500_000, out=0)], p, now=NOW)
    lines = render_runway(r, "Codex")
    assert "  used:     500.0k / 2.0M tokens" in lines


# --------------------------------------------------------------------------- #
# compact_line
# --------------------------------------------------------------------------- #
def _rw(status, used_fraction=0.5, runway_days=2.0):
    return Runway(tool="t", window_id="w", unit=Unit.AIU, now=NOW, window_start=NOW, resets_at=None, used=1.0,
                  allowance=2.0, used_fraction=used_fraction, time_fraction=None, pace_ratio=None,
                  burn_per_day_avg=None, burn_per_day_ema=None, runway_days=runway_days, days_left=None,
                  projected_exhaustion=None, status=status)


@pytest.mark.parametrize("status, icon", [
    (Status.OK, "OK"), (Status.WARN, "WARN"), (Status.CRITICAL, "CRIT"), (Status.EXHAUSTED, "OUT"),
    (Status.UNLIMITED, "inf"), (Status.UNKNOWN, "?"),
])
def test_compact_line_icons(status, icon):
    line = compact_line(_rw(status), "Tool")
    assert line.endswith(f"  {icon}") and "\n" not in line
    assert line.startswith("Tool" + " " * 14 + " [")


def test_compact_line_contents():
    line = compact_line(_rw(Status.OK, 0.5, 2.0), "Tool")
    assert "[##########----------]  50.0%" in line
    assert "runway   2.0d  OK" in line
    assert compact_line(_rw(Status.UNKNOWN, None, None), "T").count("?") == 21   # bar + icon
    assert "runway    n/a" in compact_line(_rw(Status.UNLIMITED, None, None), "T")
    assert "runway    inf" in compact_line(_rw(Status.OK, 0.0, math.inf), "T")
    long_name = compact_line(_rw(Status.OK), "A very long display name indeed")
    assert long_name.startswith("A very long display name indeed [")


# --------------------------------------------------------------------------- #
# summaries
# --------------------------------------------------------------------------- #
def _events():
    return [
        make_event(0, model="claude-sonnet-5", usd=1.0, session="a", inp=100, out=10, cr=1000, cw=50, reasoning=5),
        make_event(1, model="claude-haiku-4-5-20260101", usd=0.25, session="b", agent="sub1", inp=10, out=1),
        make_event(2, model="claude-haiku-4-5", usd=0.25, session="b", agent="sub2", inp=10, out=1),
        make_event(3, model="mystery", usd=None, session="c", inp=1, out=1),
    ]


def test_summarize_totals():
    s = summarize(_events())
    assert s["calls"] == 4 and s["input"] == 121 and s["output"] == 13
    assert s["cache_read"] == 1000 and s["cache_write"] == 50 and s["reasoning"] == 5
    assert s["usd"] == pytest.approx(1.5) and s["usd_known"] == 3
    assert s["sessions"] == {"a", "b", "c"} and s["agents"] == {"sub1", "sub2"}
    empty = summarize([])
    assert empty["calls"] == 0 and empty["usd"] == 0.0 and empty["sessions"] == set()


def test_render_summary_lines():
    lines = render_summary("Totals", _events())
    assert lines[0] == "Totals:"
    assert "  calls:            4  (sessions 3, sub-agents 2)" in lines
    assert "  input tokens:     121" in lines
    assert "  reasoning tokens: 5" in lines
    assert "  total tokens:     1.2k" in lines
    assert "  tokens/call:      296" in lines
    assert "  API-equivalent:   $1.50  (priced 3/4 calls)" in lines


def test_render_summary_omits_optional_lines():
    lines = render_summary("Empty", [])
    assert lines[-1] == "  total tokens:     0"
    assert not any("reasoning" in ln or "tokens/call" in ln or "API-equivalent" in ln for ln in lines)
    full = render_summary("Full coverage", _events()[:3])
    assert "  API-equivalent:   $1.50" in full and not any("priced" in ln for ln in full)


def test_by_model_groups_normalised_and_sorts_by_usd():
    rows = by_model(_events())
    names = [m for m, _ in rows]
    assert names == ["claude-sonnet-5", "claude-haiku-4-5", "mystery"]
    haiku = dict(rows)["claude-haiku-4-5"]
    assert haiku["calls"] == 2 and haiku["usd"] == pytest.approx(0.5)
    # blank model ids are grouped under (unknown)
    rows = by_model([make_event(0, model="", usd=None)])
    assert rows[0][0] == "(unknown)"


def test_render_by_model_table_and_shares():
    lines = render_by_model(_events())
    assert lines[0].split() == ["model", "calls", "in", "out", "cache", "r/w", "API-eq", "$", "share"]
    assert len(lines) == 4
    sonnet = lines[1]
    assert sonnet.startswith("  claude-sonnet-5") and sonnet.endswith("1.00    67%")
    assert "1.0k/50" in sonnet
    assert lines[3].startswith("  mystery") and lines[3].endswith("0.00     0%")
    # no USD at all: shares divide by 1.0 instead of crashing
    zero = render_by_model([make_event(0, model="x", usd=None)])
    assert zero[1].endswith("0.00     0%")


def test_render_sessions_table_ordering_limit_and_truncation():
    evs = [
        make_event(5, session="old", usd=1.0),
        make_event(0, session="s" * 50, usd=2.0),
        make_event(1, session="mid", usd=None), make_event(0.5, session="mid", usd=0.5),
        make_event(2, session="", usd=None),
    ]
    lines = render_sessions_table(evs)
    assert lines[0].split() == ["session", "calls", "tokens", "API-eq", "$", "last", "activity"]
    ids = [ln.split()[0] for ln in lines[1:]]
    assert ids == ["s" * 36, "mid", "(none)", "old"]           # newest activity first, id cut to 36
    mid = lines[2]
    assert mid.split()[1] == "2" and mid.endswith((NOW - timedelta(days=0.5)).strftime("%Y-%m-%d %H:%M"))
    assert len(render_sessions_table(evs, limit=2)) == 3
    assert render_sessions_table([]) == [lines[0]]


def test_render_sessions_table_same_timestamp_does_not_crash():
    ts = datetime(2026, 9, 15, tzinfo=timezone.utc)
    evs = [make_event(0, now=ts, session="a"), make_event(0, now=ts, session="b")]
    ids = [ln.split()[0] for ln in render_sessions_table(evs)[1:]]
    assert sorted(ids) == ["a", "b"]
