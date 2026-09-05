from datetime import datetime, timedelta, timezone

from token_finops.core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Status, Unit, UsageEvent
from token_finops.core.pricing import estimate_usd, normalize_model_id
from token_finops.core.runway import (binding_constraint, calendar_month_window, compute_runway,
                                      ema_daily_burn)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def ev(days_ago: float, aiu: float = 100.0, tool="copilot") -> UsageEvent:
    return UsageEvent(ts_utc=NOW - timedelta(days=days_ago), tool=tool, model_raw="gpt-5",
                      input_tokens=1000, output_tokens=200, native_cost=aiu, native_unit=Unit.AIU)


def policy(allowance=3000.0) -> BudgetPolicy:
    return BudgetPolicy(tool="copilot", window_id="month", unit=Unit.AIU,
                        cycle=CycleKind.CALENDAR_MONTH_UTC, allowance=allowance)


def test_calendar_month_window_resets_first_utc():
    start, reset = calendar_month_window(1, NOW)
    assert start == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert reset == datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_runway_ok_when_on_pace():
    # 14.5 days elapsed of 30 → ~48 % of time; used 40 % of budget → on pace
    events = [ev(d, aiu=100.0) for d in range(12)]  # 1200 AIU
    r = compute_runway(events, policy(3000.0), now=NOW)
    assert r.used == 1200.0
    assert r.status == Status.OK
    assert r.pace_ratio is not None and r.pace_ratio < 1.0
    assert r.runway_days is not None and r.runway_days > r.days_left


def test_runway_critical_when_projected_to_run_out():
    events = [ev(d, aiu=200.0) for d in range(14)]  # 2800 of 3000 with half the month left
    r = compute_runway(events, policy(3000.0), now=NOW)
    assert r.status in (Status.CRITICAL, Status.EXHAUSTED)
    assert r.runway_days < r.days_left


def test_runway_unlimited_without_allowance():
    r = compute_runway([ev(1)], policy(None), now=NOW)
    assert r.status == Status.UNLIMITED
    assert r.runway_days is None


def test_provider_snapshot_overrides_local_sum():
    p = BudgetPolicy(tool="codex", window_id="5h", unit=Unit.PERCENT, cycle=CycleKind.ROLLING,
                     window_length=timedelta(hours=5), allowance=1.0, source_of_truth="provider_pct")
    q = QuotaSnapshot(tool="codex", window_id="5h", observed_at=NOW, used_fraction=0.8,
                      resets_at=NOW + timedelta(hours=2), source="codex_rollout")
    r = compute_runway([], p, now=NOW, quota=q)
    assert r.used_fraction == 0.8
    assert r.status == Status.WARN
    assert "provider" in r.notes[0]


def test_percent_without_snapshot_is_unknown():
    p = BudgetPolicy(tool="claude_code", window_id="5h", unit=Unit.PERCENT, cycle=CycleKind.ROLLING,
                     window_length=timedelta(hours=5), allowance=1.0, source_of_truth="provider_pct")
    assert compute_runway([], p, now=NOW).status == Status.UNKNOWN


def test_ema_reacts_to_recent_burst():
    quiet = {(NOW - timedelta(days=d)).date(): 10.0 for d in range(1, 20)}
    burst = dict(quiet)
    burst[NOW.date()] = 500.0
    assert ema_daily_burn(burst, NOW) > ema_daily_burn(quiet, NOW) * 3


def test_binding_constraint_picks_shortest_runway():
    a = compute_runway([ev(d, aiu=100.0) for d in range(12)], policy(3000.0), now=NOW)
    b = compute_runway([ev(d, aiu=250.0) for d in range(12)], policy(3000.0), now=NOW)
    assert binding_constraint([a, b]) is b


def test_normalize_model_id():
    assert normalize_model_id("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5"
    assert normalize_model_id("anthropic/claude-opus-4-1") == "claude-opus-4-1"
    assert normalize_model_id("us.anthropic.claude-sonnet-4-v1:0") == "claude-sonnet-4"
    assert normalize_model_id("gpt-5-2025-08-07") == "gpt-5"


def test_estimate_usd_cache_pricing():
    base = estimate_usd("claude-sonnet-5", input_tokens=1_000_000)
    cached = estimate_usd("claude-sonnet-5", cache_read_tokens=1_000_000)
    assert abs(base - 2.0) < 1e-9
    assert abs(cached - 0.2) < 1e-9          # 10 % of input
    assert estimate_usd("ollama/qwen3:latest", 1000, 1000) is None
