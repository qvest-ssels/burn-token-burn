"""core/runway.py: window boundaries, burn estimates, status thresholds,
provider snapshot override and the percent-window slope estimator."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest
from conftest import NOW, make_event, month_policy, percent_policy

from token_finops_cli.core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Runway, Status, Unit
from token_finops_cli.core.runway import (_percent_runway, _status, binding_constraint, calendar_month_window,
                                          compute_runway, daily_buckets, daily_window, ema_daily_burn,
                                          native_amount, rolling_window, utcnow, window_for)

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# windows
# --------------------------------------------------------------------------- #
def test_utcnow_is_aware_utc():
    n = utcnow()
    assert n.tzinfo is not None and n.utcoffset() == timedelta(0)


@pytest.mark.parametrize("now, cycle_day, start, reset", [
    (datetime(2026, 9, 15, tzinfo=UTC), 1, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)),
    # exactly on the boundary: the new cycle has begun
    (datetime(2026, 9, 1, 0, 0, tzinfo=UTC), 1, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)),
    # December -> January rollover
    (datetime(2026, 12, 20, tzinfo=UTC), 1, datetime(2026, 12, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    # cycle_day 15: before the 15th the cycle started last month
    (datetime(2026, 9, 10, tzinfo=UTC), 15, datetime(2026, 8, 15, tzinfo=UTC), datetime(2026, 9, 15, tzinfo=UTC)),
    (datetime(2026, 9, 15, tzinfo=UTC), 15, datetime(2026, 9, 15, tzinfo=UTC), datetime(2026, 10, 15, tzinfo=UTC)),
    # cycle_day 15 in January: previous cycle started in December of the previous year
    (datetime(2027, 1, 5, tzinfo=UTC), 15, datetime(2026, 12, 15, tzinfo=UTC), datetime(2027, 1, 15, tzinfo=UTC)),
])
def test_calendar_month_window(now, cycle_day, start, reset):
    assert calendar_month_window(cycle_day, now) == (start, reset)


def test_calendar_month_window_length_is_whole_months():
    start, reset = calendar_month_window(1, datetime(2026, 2, 10, tzinfo=UTC))
    assert (reset - start).days == 28
    start, reset = calendar_month_window(1, datetime(2028, 2, 10, tzinfo=UTC))
    assert (reset - start).days == 29  # leap year


def test_rolling_window_has_no_reset():
    start, reset = rolling_window(timedelta(hours=5), NOW)
    assert start == NOW - timedelta(hours=5) and reset is None


def test_daily_window_utc_midnights():
    start, end = daily_window(datetime(2026, 9, 15, 23, 59, tzinfo=UTC))
    assert start == datetime(2026, 9, 15, tzinfo=UTC)
    assert end == datetime(2026, 9, 16, tzinfo=UTC)


def test_daily_window_other_timezone():
    tz = timezone(timedelta(hours=-7))
    # 03:00 UTC is still the previous local day in UTC-7
    start, end = daily_window(datetime(2026, 9, 15, 3, 0, tzinfo=UTC), tz=tz)
    assert start == datetime(2026, 9, 14, 7, 0, tzinfo=UTC)
    assert end - start == timedelta(days=1)


def test_window_for_dispatch():
    p = month_policy(cycle_day=5)
    assert window_for(p, NOW) == calendar_month_window(5, NOW)
    rolling = percent_policy(hours=7 * 24)
    assert window_for(rolling, NOW) == (NOW - timedelta(days=7), None)
    rolling_default = BudgetPolicy("t", "5h", Unit.PERCENT, CycleKind.ROLLING)
    assert window_for(rolling_default, NOW) == (NOW - timedelta(hours=5), None)
    daily = BudgetPolicy("gemini", "day", Unit.REQUESTS, CycleKind.DAILY)
    assert window_for(daily, NOW) == daily_window(NOW)
    sliding = BudgetPolicy("x", "30d", Unit.USD, CycleKind.SLIDING_FROM_FIRST_USE)
    assert window_for(sliding, NOW) == (NOW - timedelta(days=30), None)
    sliding_len = BudgetPolicy("x", "10d", Unit.USD, CycleKind.SLIDING_FROM_FIRST_USE,
                               window_length=timedelta(days=10))
    assert window_for(sliding_len, NOW) == (NOW - timedelta(days=10), None)
    none = BudgetPolicy("local", "none", Unit.MINUTES, CycleKind.NONE)
    start, reset = window_for(none, NOW)
    assert start == datetime.min.replace(tzinfo=UTC) and reset is None


# --------------------------------------------------------------------------- #
# native_amount / buckets / EMA
# --------------------------------------------------------------------------- #
def test_native_amount_every_unit():
    ev = make_event(aiu=12.5, usd=0.7, inp=100, out=50, cr=25, cw=25, duration_ms=90_000)
    assert native_amount(ev, Unit.AIU) == 12.5
    # asking for USD on an AIU-costed event falls back to the USD estimate
    assert native_amount(ev, Unit.USD) == 0.7
    assert native_amount(ev, Unit.REQUESTS) == 1.0
    assert native_amount(ev, Unit.TOKENS) == 200.0
    assert native_amount(ev, Unit.MINUTES) == 1.5
    assert native_amount(ev, Unit.PERCENT) == 0.0


def test_native_amount_usd_native_and_missing():
    usd_ev = make_event(aiu=0.42, usd=9.9, native_unit=Unit.USD)
    assert native_amount(usd_ev, Unit.USD) == 0.42          # native USD wins over the estimate
    assert native_amount(usd_ev, Unit.AIU) == 0.0            # unit mismatch, no AIU estimate exists
    bare = make_event(aiu=None, usd=None, duration_ms=None)
    assert native_amount(bare, Unit.USD) == 0.0
    assert native_amount(bare, Unit.AIU) == 0.0
    assert native_amount(bare, Unit.MINUTES) == 0.0


def test_daily_buckets_groups_by_utc_date():
    evs = [make_event(0, aiu=1.0), make_event(0.1, aiu=2.0), make_event(1.0, aiu=4.0)]
    b = daily_buckets(evs, Unit.AIU)
    assert b == {NOW.date(): 3.0, (NOW - timedelta(days=1)).date(): 4.0}
    assert daily_buckets([], Unit.AIU) == {}
    assert daily_buckets(evs, Unit.REQUESTS)[NOW.date()] == 2.0


def test_ema_none_on_empty_and_constant_is_identity():
    assert ema_daily_burn({}, NOW) is None
    const = {(NOW - timedelta(days=d)).date(): 10.0 for d in range(0, 40)}
    assert ema_daily_burn(const, NOW) == pytest.approx(10.0)


def test_ema_burst_detection_and_decay():
    quiet = {(NOW - timedelta(days=d)).date(): 10.0 for d in range(1, 20)}
    burst_today = {**quiet, NOW.date(): 500.0}
    burst_old = {**quiet, (NOW - timedelta(days=15)).date(): 500.0}
    ema_quiet = ema_daily_burn(quiet, NOW)
    assert ema_quiet is not None and ema_quiet < 10.0                # today is zero-filled
    assert ema_daily_burn(burst_today, NOW) > 3 * ema_quiet
    # an old burst is mostly decayed away but still weighs more than nothing
    assert ema_quiet < ema_daily_burn(burst_old, NOW) < ema_daily_burn(burst_today, NOW)


def test_ema_only_looks_back_three_spans():
    ancient = {(NOW - timedelta(days=60)).date(): 1e9}
    assert ema_daily_burn(ancient, NOW) == 0.0
    # explicit span changes the alpha: a shorter span reacts more strongly to today
    buckets = {(NOW - timedelta(days=d)).date(): 10.0 for d in range(1, 30)}
    buckets[NOW.date()] = 100.0
    assert ema_daily_burn(buckets, NOW, span_days=3) > ema_daily_burn(buckets, NOW, span_days=14)


# --------------------------------------------------------------------------- #
# _status
# --------------------------------------------------------------------------- #
P = month_policy(1000.0)


@pytest.mark.parametrize("used, runway, left, expected", [
    (0.10, 100.0, 15.0, Status.OK),
    (0.7499, 100.0, 15.0, Status.OK),
    (0.75, 100.0, 15.0, Status.WARN),          # warn threshold inclusive
    (0.8999, 100.0, 15.0, Status.WARN),
    (0.90, 100.0, 15.0, Status.CRITICAL),      # critical threshold inclusive
    (1.0, 100.0, 15.0, Status.EXHAUSTED),
    (1.5, None, None, Status.EXHAUSTED),
    (0.10, 5.0, 15.0, Status.CRITICAL),         # projected to run out before reset
    (0.10, 15.0, 15.0, Status.OK),              # exactly making it to reset is fine
    (0.10, 5.0, None, Status.OK),               # no reset known -> no projection
    (0.10, None, 15.0, Status.OK),
    (0.10, math.inf, 15.0, Status.OK),
    (None, None, None, Status.UNKNOWN),
])
def test_status_thresholds(used, runway, left, expected):
    assert _status(used, runway, left, P) is expected


def test_status_unlimited_beats_everything():
    unlimited = month_policy(None)
    assert _status(1.5, 0.0, 10.0, unlimited) is Status.UNLIMITED
    assert _status(None, None, None, unlimited) is Status.UNLIMITED


def test_status_custom_thresholds():
    p = month_policy(1000.0, warn_at=0.5, critical_at=0.6)
    assert _status(0.55, None, None, p) is Status.WARN
    assert _status(0.61, None, None, p) is Status.CRITICAL


# --------------------------------------------------------------------------- #
# compute_runway with local events
# --------------------------------------------------------------------------- #
def test_compute_runway_only_counts_events_in_window():
    evs = [make_event(1, aiu=100.0), make_event(20, aiu=999.0)]  # 20 days ago = August
    r = compute_runway(evs, month_policy(3000.0), now=NOW)
    assert r.used == 100.0
    assert r.window_start == datetime(2026, 9, 1, tzinfo=UTC)
    assert r.resets_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert r.used_fraction == pytest.approx(100 / 3000)
    assert r.time_fraction == pytest.approx(14.5 / 30)
    assert r.pace_ratio == pytest.approx(r.used_fraction / r.time_fraction)
    assert r.days_left == pytest.approx(15.5)
    assert r.burn_per_day_avg == pytest.approx(100.0 / 14.5)
    assert r.source_of_truth == "local_sum" and r.notes == []


def test_compute_runway_no_events_infinite_runway():
    r = compute_runway([], month_policy(3000.0), now=NOW)
    assert r.used == 0.0 and r.burn_per_day_avg is None and r.burn_per_day_ema is None
    assert r.runway_days == math.inf and r.projected_exhaustion is None
    assert r.status is Status.OK and not r.is_binding


def test_compute_runway_pessimistic_max_of_avg_and_ema():
    # quiet month, then a burst today: EMA > cycle average, runway must use the EMA
    evs = [make_event(d, aiu=10.0) for d in range(1, 14)] + [make_event(0, aiu=800.0)]
    r = compute_runway(evs, month_policy(3000.0), now=NOW)
    assert r.burn_per_day_ema > r.burn_per_day_avg
    remaining = 3000.0 - r.used
    assert r.runway_days == pytest.approx(remaining / r.burn_per_day_ema)
    assert r.projected_exhaustion == NOW + timedelta(days=r.runway_days)
    # front-loaded spending that went quiet: the cycle average is the pessimistic one
    steady = [make_event(d, aiu=200.0) for d in range(8, 14)]
    r2 = compute_runway(steady, month_policy(3000.0), now=NOW)
    assert r2.burn_per_day_avg > r2.burn_per_day_ema
    assert r2.runway_days == pytest.approx((3000.0 - r2.used) / r2.burn_per_day_avg)


def test_compute_runway_exhausted_and_over_budget():
    evs = [make_event(1, aiu=1600.0), make_event(2, aiu=1600.0)]
    r = compute_runway(evs, month_policy(3000.0), now=NOW)
    assert r.status is Status.EXHAUSTED and r.is_binding
    assert r.runway_days == 0.0 and r.projected_exhaustion == NOW
    assert r.used_fraction > 1.0


def test_compute_runway_over_budget_without_burn_rate():
    """remaining <= 0 but every in-window event has zero cost: runway 0, not inf."""
    evs = [make_event(1, aiu=0.0)]
    r = compute_runway(evs, month_policy(-1.0), now=NOW)  # negative allowance makes remaining < 0
    assert r.runway_days == 0.0 and r.projected_exhaustion == NOW


def test_compute_runway_unlimited_policy():
    r = compute_runway([make_event(1, aiu=100.0)], month_policy(None), now=NOW)
    assert r.status is Status.UNLIMITED
    assert r.used == 100.0 and r.used_fraction is None and r.pace_ratio is None
    assert r.runway_days is None and r.allowance is None


def test_compute_runway_rolling_window_no_reset():
    p = BudgetPolicy("codex", "5h", Unit.TOKENS, CycleKind.ROLLING, allowance=1_000_000,
                     window_length=timedelta(hours=5))
    evs = [make_event(0.1, inp=100_000, out=0), make_event(2, inp=999_999, out=0)]
    r = compute_runway(evs, p, now=NOW)
    assert r.used == 100_000 and r.resets_at is None
    assert r.days_left is None and r.time_fraction is None and r.pace_ratio is None
    assert r.burn_per_day_avg == pytest.approx(100_000 / (5 / 24))
    assert r.status is Status.OK
    assert r.runway_days == pytest.approx(900_000 / r.burn_per_day_avg)


def test_compute_runway_daily_requests_window():
    p = BudgetPolicy("gemini_cli", "day", Unit.REQUESTS, CycleKind.DAILY, allowance=1000)
    now = datetime(2026, 9, 15, 6, 0, tzinfo=UTC)  # 25 % into the day
    evs = [make_event(0, now=now), make_event(0.1, now=now), make_event(0.5, now=now)]  # last one is yesterday
    r = compute_runway(evs, p, now=now)
    assert r.used == 2.0 and r.time_fraction == pytest.approx(0.25)
    assert r.resets_at == datetime(2026, 9, 16, tzinfo=UTC)
    assert r.pace_ratio == pytest.approx((2 / 1000) / 0.25)


def test_compute_runway_uses_utcnow_by_default():
    r = compute_runway([], month_policy(10.0))
    assert abs((r.now - utcnow()).total_seconds()) < 5


def test_compute_runway_projected_to_run_out_is_critical_below_thresholds():
    # 40 % used after half the month, but a burst today makes the EMA project exhaustion before reset
    evs = [make_event(d + 0.5, aiu=50.0) for d in range(1, 14)] + [make_event(0, aiu=550.0)]
    r = compute_runway(evs, month_policy(3000.0), now=NOW)
    assert r.used_fraction < 0.75
    assert r.runway_days < r.days_left
    assert r.status is Status.CRITICAL


# --------------------------------------------------------------------------- #
# provider snapshot override for non-percent units (hybrid / provider_pct)
# --------------------------------------------------------------------------- #
def test_provider_snapshot_overrides_local_sum_for_native_units():
    p = BudgetPolicy("gemini_cli", "day", Unit.REQUESTS, CycleKind.DAILY, allowance=1000,
                     source_of_truth="hybrid")
    q = QuotaSnapshot("gemini_cli", "day", NOW, used_fraction=0.5, resets_at=NOW + timedelta(hours=3),
                      source="gemini_api")
    r = compute_runway([make_event(0), make_event(0.01)], p, now=NOW, quota=q)
    assert r.used_fraction == 0.5
    assert r.used == 500.0                     # rescaled to the allowance
    assert r.resets_at == NOW + timedelta(hours=3)
    assert r.notes == ["used% from provider (gemini_api)"]
    assert r.days_left == pytest.approx(3 / 24)


def test_provider_snapshot_with_stale_reset_keeps_policy_reset():
    p = BudgetPolicy("gemini_cli", "day", Unit.REQUESTS, CycleKind.DAILY, allowance=1000,
                     source_of_truth="hybrid")
    q = QuotaSnapshot("gemini_cli", "day", NOW, used_fraction=0.5, resets_at=NOW - timedelta(hours=1))
    r = compute_runway([], p, now=NOW, quota=q)
    assert r.resets_at == datetime(2026, 9, 16, tzinfo=UTC)


def test_provider_snapshot_ignored_when_local_sum_is_source_of_truth():
    p = month_policy(3000.0)  # source_of_truth = local_sum
    q = QuotaSnapshot("copilot", "month", NOW, used_fraction=0.99)
    r = compute_runway([make_event(1, aiu=100.0)], p, now=NOW, quota=q)
    assert r.used_fraction == pytest.approx(100 / 3000) and r.notes == []


def test_provider_snapshot_without_fraction_is_ignored():
    p = BudgetPolicy("x", "day", Unit.REQUESTS, CycleKind.DAILY, allowance=10, source_of_truth="hybrid")
    q = QuotaSnapshot("x", "day", NOW, used_fraction=None, used_units=3)
    r = compute_runway([make_event(0)], p, now=NOW, quota=q)
    assert r.used_fraction == pytest.approx(0.1) and r.notes == []


def test_provider_snapshot_without_allowance_keeps_local_used():
    p = BudgetPolicy("x", "day", Unit.REQUESTS, CycleKind.DAILY, allowance=None, source_of_truth="provider_pct")
    q = QuotaSnapshot("x", "day", NOW, used_fraction=0.3)
    r = compute_runway([make_event(0), make_event(0)], p, now=NOW, quota=q)
    assert r.used == 2.0 and r.used_fraction == 0.3 and r.status is Status.UNLIMITED


# --------------------------------------------------------------------------- #
# percent windows
# --------------------------------------------------------------------------- #
def snap(used, *, at=NOW, reset=NOW + timedelta(hours=2), source="claude_statusline"):
    return QuotaSnapshot("claude_code", "5h", at, used_fraction=used, resets_at=reset, source=source)


def test_percent_without_snapshot_is_unknown_with_hint():
    r = compute_runway([make_event(0)], percent_policy(), now=NOW)
    assert r.status is Status.UNKNOWN and r.unit is Unit.PERCENT
    assert r.used == 0.0 and r.used_fraction is None and r.resets_at is None
    assert r.window_start == NOW - timedelta(hours=5)
    assert "collect-statusline" in r.notes[0]
    # a snapshot without a fraction is as good as none
    r2 = compute_runway([], percent_policy(), now=NOW, quota=snap(None))
    assert r2.status is Status.UNKNOWN


def test_percent_single_snapshot_geometry():
    r = compute_runway([], percent_policy(), now=NOW, quota=snap(0.4))
    assert r.source_of_truth == "provider_pct" and r.allowance == 1.0
    assert r.used == 0.4 and r.used_fraction == 0.4
    assert r.resets_at == NOW + timedelta(hours=2)
    assert r.window_start == NOW - timedelta(hours=3)
    assert r.time_fraction == pytest.approx(0.6)
    assert r.pace_ratio == pytest.approx(0.4 / 0.6)
    assert r.days_left == pytest.approx(2 / 24)
    assert r.burn_per_day_avg is None and r.burn_per_day_ema is None and r.runway_days is None
    assert r.status is Status.OK
    assert r.notes[0].startswith("used% from provider (claude_statusline, observed 12:00 UTC)")
    assert any("needs >=2 snapshots" in n for n in r.notes)


def test_percent_status_thresholds_from_fraction_alone():
    assert compute_runway([], percent_policy(), now=NOW, quota=snap(0.75)).status is Status.WARN
    assert compute_runway([], percent_policy(), now=NOW, quota=snap(0.9)).status is Status.CRITICAL
    assert compute_runway([], percent_policy(), now=NOW, quota=snap(1.0)).status is Status.EXHAUSTED
    assert compute_runway([], percent_policy(allowance=None), now=NOW, quota=snap(0.9)).status is Status.UNLIMITED


def test_percent_stale_reset_in_the_past_is_dropped():
    r = compute_runway([], percent_policy(), now=NOW, quota=snap(0.4, reset=NOW - timedelta(minutes=1)))
    assert r.resets_at is None and r.days_left is None
    assert r.time_fraction is None and r.pace_ratio is None
    assert r.window_start == NOW - timedelta(hours=5)
    assert r.status is Status.OK


def test_percent_history_with_fewer_than_two_points_gives_no_burn():
    q = snap(0.5)
    assert compute_runway([], percent_policy(), now=NOW, quota=q, quota_history=None).runway_days is None
    assert compute_runway([], percent_policy(), now=NOW, quota=q, quota_history=[]).runway_days is None
    assert compute_runway([], percent_policy(), now=NOW, quota=q, quota_history=[q]).runway_days is None


def test_percent_two_snapshots_give_slope_and_runway():
    h = [snap(0.2, at=NOW - timedelta(hours=1)), snap(0.5, at=NOW)]
    r = compute_runway([], percent_policy(), now=NOW, quota=h[-1], quota_history=h)
    assert r.burn_per_day_avg == pytest.approx(0.3 * 24)          # 30 % per hour
    assert r.runway_days == pytest.approx(0.5 / (0.3 * 24))         # 1h40m
    assert r.projected_exhaustion == NOW + timedelta(days=r.runway_days)
    assert r.days_left == pytest.approx(2 / 24)
    assert r.status is Status.CRITICAL                             # runs out before the reset
    assert not any("needs >=2 snapshots" in n for n in r.notes)


def test_percent_slow_burn_stays_ok():
    h = [snap(0.20, at=NOW - timedelta(hours=1)), snap(0.21, at=NOW)]
    r = compute_runway([], percent_policy(), now=NOW, quota=h[-1], quota_history=h)
    assert r.runway_days > r.days_left and r.status is Status.OK


def test_percent_history_uses_first_and_last_point_unsorted_input():
    h = [snap(0.5, at=NOW), snap(0.2, at=NOW - timedelta(hours=2)), snap(0.35, at=NOW - timedelta(hours=1))]
    r = compute_runway([], percent_policy(), now=NOW, quota=h[0], quota_history=h)
    assert r.burn_per_day_avg == pytest.approx(0.15 * 24)


def test_percent_history_from_other_window_is_ignored():
    other_reset = NOW - timedelta(hours=3)  # previous window's reset time
    h = [snap(0.1, at=NOW - timedelta(hours=4), reset=other_reset),
         snap(0.9, at=NOW - timedelta(hours=3, minutes=30), reset=other_reset),
         snap(0.5, at=NOW)]
    r = compute_runway([], percent_policy(), now=NOW, quota=h[-1], quota_history=h)
    assert r.runway_days is None
    assert any("needs >=2 snapshots" in n for n in r.notes)


def test_percent_history_ignores_snapshots_without_fraction_and_same_instant():
    h = [snap(None, at=NOW - timedelta(hours=1)), snap(0.5, at=NOW), snap(0.6, at=NOW)]
    r = compute_runway([], percent_policy(), now=NOW, quota=h[-1], quota_history=h)
    assert r.runway_days is None


def test_percent_decreasing_or_flat_used_gives_no_burn():
    flat = [snap(0.5, at=NOW - timedelta(hours=1)), snap(0.5, at=NOW)]
    assert compute_runway([], percent_policy(), now=NOW, quota=flat[-1], quota_history=flat).runway_days is None
    down = [snap(0.7, at=NOW - timedelta(hours=1)), snap(0.5, at=NOW)]
    r = compute_runway([], percent_policy(), now=NOW, quota=down[-1], quota_history=down)
    assert r.runway_days is None and r.burn_per_day_avg is None and r.status is Status.OK


def test_percent_runway_when_current_reset_is_stale_uses_all_history():
    """With a stale current snapshot there is no window to match against;
    the slope still comes from the history (documented behaviour)."""
    stale = snap(0.5, reset=NOW - timedelta(minutes=5))
    h = [snap(0.2, at=NOW - timedelta(hours=1), reset=NOW + timedelta(hours=9)), stale]
    r = _percent_runway(percent_policy(), NOW, stale, h)
    assert r.burn_per_day_avg == pytest.approx(0.3 * 24)
    assert r.days_left is None and r.status is Status.OK  # no reset -> no projection against it


def test_percent_exhausted_with_history_has_zero_runway():
    h = [snap(0.8, at=NOW - timedelta(hours=1)), snap(1.0, at=NOW)]
    r = compute_runway([], percent_policy(), now=NOW, quota=h[-1], quota_history=h)
    assert r.runway_days == 0.0 and r.status is Status.EXHAUSTED


def test_percent_uses_default_five_hour_length_when_policy_has_none():
    p = BudgetPolicy("claude_code", "5h", Unit.PERCENT, CycleKind.ROLLING, allowance=1.0,
                     source_of_truth="provider_pct")
    r = compute_runway([], p, now=NOW, quota=snap(0.5))
    assert r.window_start == NOW + timedelta(hours=2) - timedelta(hours=5)


# --------------------------------------------------------------------------- #
# binding constraint
# --------------------------------------------------------------------------- #
def _rw(runway_days, status=Status.OK, tool="t"):
    return Runway(tool=tool, window_id="w", unit=Unit.AIU, now=NOW, window_start=NOW, resets_at=None,
                  used=0.0, allowance=1.0, used_fraction=0.0, time_fraction=None, pace_ratio=None,
                  burn_per_day_avg=None, burn_per_day_ema=None, runway_days=runway_days, days_left=None,
                  projected_exhaustion=None, status=status)


def test_binding_constraint_picks_min_and_ignores_unlimited_and_unknown():
    a, b, c = _rw(10.0, tool="a"), _rw(2.0, tool="b"), _rw(0.5, Status.UNLIMITED, tool="c")
    d = _rw(None, Status.UNKNOWN, tool="d")
    assert binding_constraint([a, b, c, d]) is b
    assert binding_constraint([a, _rw(math.inf)]) is a
    assert binding_constraint([]) is None
    assert binding_constraint([c, d]) is None
    exhausted = _rw(0.0, Status.EXHAUSTED)
    assert binding_constraint([a, exhausted]) is exhausted


def test_binding_constraint_is_a_generator_friendly_api():
    assert binding_constraint(r for r in [_rw(3.0), _rw(1.0)]).runway_days == 1.0


def test_runway_is_binding_property():
    assert _rw(1.0, Status.WARN).is_binding and _rw(1.0, Status.CRITICAL).is_binding
    assert _rw(1.0, Status.EXHAUSTED).is_binding
    assert not _rw(1.0, Status.OK).is_binding and not _rw(1.0, Status.UNKNOWN).is_binding


def test_model_helpers():
    ev = make_event(inp=1, out=2, cr=3, cw=4, model="anthropic/claude-sonnet-5-20260101")
    assert ev.total_tokens == 10
    assert ev.model_norm == "claude-sonnet-5"
    assert date(2026, 9, 15) == ev.ts_utc.date()
