"""Runway math, generalised from token-finops-cli's Copilot-only version.

Two burn estimates are computed:
- cycle average (what the original tool did): used / elapsed_days
- EMA (exponential moving average over daily buckets): reacts to a burst
  yesterday instead of being diluted by three quiet weeks.

The runway shown to the user is the *more pessimistic* of the two so a burst
is visible immediately, while the cycle average is still reported.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from .model import BudgetPolicy, CycleKind, QuotaSnapshot, Runway, Status, Unit, UsageEvent


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Window boundaries
# --------------------------------------------------------------------------- #
def calendar_month_window(cycle_day: int, now: datetime) -> tuple[datetime, datetime]:
    """Start and next reset of a monthly cycle that resets at 00:00 UTC on
    `cycle_day`. Copilot resets on the 1st; the original tool let users
    override the day, we keep that."""
    year, month = now.year, now.month
    if now.day < cycle_day:
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    start = datetime(year, month, cycle_day, tzinfo=timezone.utc)
    nm, ny = month + 1, year
    if nm == 13:
        nm, ny = 1, ny + 1
    reset = datetime(ny, nm, cycle_day, tzinfo=timezone.utc)
    return start, reset


def rolling_window(length: timedelta, now: datetime) -> tuple[datetime, Optional[datetime]]:
    """A rolling window has no fixed reset; we report its start and no reset."""
    return now - length, None


def daily_window(now: datetime, tz=timezone.utc) -> tuple[datetime, datetime]:
    local = now.astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def window_for(policy: BudgetPolicy, now: datetime) -> tuple[datetime, Optional[datetime]]:
    if policy.cycle == CycleKind.CALENDAR_MONTH_UTC:
        return calendar_month_window(policy.cycle_day, now)
    if policy.cycle == CycleKind.ROLLING:
        return rolling_window(policy.window_length or timedelta(hours=5), now)
    if policy.cycle == CycleKind.DAILY:
        return daily_window(now)
    if policy.cycle == CycleKind.SLIDING_FROM_FIRST_USE:
        return now - (policy.window_length or timedelta(days=30)), None
    return datetime.min.replace(tzinfo=timezone.utc), None


# --------------------------------------------------------------------------- #
# Burn estimates
# --------------------------------------------------------------------------- #
def native_amount(ev: UsageEvent, unit: Unit) -> float:
    """How much of the budget unit one event consumed."""
    if unit == Unit.AIU or unit == Unit.USD:
        if ev.native_cost is not None and ev.native_unit == unit:
            return ev.native_cost
        if unit == Unit.USD and ev.usd_estimate is not None:
            return ev.usd_estimate
        return 0.0
    if unit == Unit.REQUESTS:
        return 1.0
    if unit == Unit.TOKENS:
        return float(ev.total_tokens)
    if unit == Unit.MINUTES:
        return (ev.duration_ms or 0.0) / 60_000.0
    return 0.0


def daily_buckets(events: Iterable[UsageEvent], unit: Unit) -> dict[date, float]:
    buckets: dict[date, float] = defaultdict(float)
    for ev in events:
        buckets[ev.ts_utc.date()] += native_amount(ev, unit)
    return dict(buckets)


def ema_daily_burn(buckets: dict[date, float], now: datetime, span_days: int = 7) -> Optional[float]:
    """EMA over the last `span_days` calendar days including today (zero-filled)."""
    if not buckets:
        return None
    alpha = 2.0 / (span_days + 1)
    today = now.date()
    days = [today - timedelta(days=i) for i in range(span_days * 3, -1, -1)]
    ema = None
    for d in days:
        v = buckets.get(d, 0.0)
        ema = v if ema is None else alpha * v + (1 - alpha) * ema
    return ema


# --------------------------------------------------------------------------- #
# Runway
# --------------------------------------------------------------------------- #
def _status(used_fraction: Optional[float], runway_days: Optional[float],
            days_left: Optional[float], policy: BudgetPolicy) -> Status:
    if policy.allowance is None:
        return Status.UNLIMITED
    if used_fraction is None:
        return Status.UNKNOWN
    if used_fraction >= 1.0:
        return Status.EXHAUSTED
    # Projected to run out before reset → CRITICAL regardless of level.
    if runway_days is not None and days_left is not None and runway_days < days_left:
        return Status.CRITICAL
    if used_fraction >= policy.critical_at:
        return Status.CRITICAL
    if used_fraction >= policy.warn_at:
        return Status.WARN
    return Status.OK


def _percent_runway(policy: BudgetPolicy, now: datetime, quota: QuotaSnapshot,
                    history: Optional[list[QuotaSnapshot]]) -> Runway:
    """Rolling percent windows (Claude Code, Codex): the provider tells us
    used% and reset time; burn can only come from consecutive snapshots.

    Precedence note: `quota.resets_at` is *real* data the tool itself recorded
    (Claude Code's statusline payload, Codex's rollout `rate_limits`), so it always
    decides when the window ends. `policy.window_length` -- which a user may override
    via `budget.window_hours` / `$TOKEN_FINOPS_WINDOW_HOURS` -- only says how long the
    window is assumed to be, a span no provider reports; it is used to place the
    window *start* (and therefore pace), never to move a known reset time.
    """
    length = policy.window_length or timedelta(hours=5)
    reset = quota.resets_at
    if reset is not None and reset <= now:
        reset = None  # stale snapshot: the window it described has already reset
    start = (reset - length) if reset else (now - length)
    used_fraction = quota.used_fraction
    notes = [f"used% from provider ({quota.source}, observed {quota.observed_at:%H:%M} UTC)"]
    days_left = (reset - now).total_seconds() / 86400.0 if reset else None
    time_fraction = min(1.0, max(0.0, (now - start).total_seconds() / length.total_seconds())) if reset else None
    pace = (used_fraction / time_fraction) if (used_fraction is not None and time_fraction) else None

    burn_per_day = None
    runway_days = None
    projected = None
    if history and len(history) >= 2:
        # slope over snapshots in the same window (used% not decreasing)
        pts = sorted([h for h in history if h.used_fraction is not None
                      and (reset is None or h.resets_at == quota.resets_at)],
                     key=lambda h: h.observed_at)
        if len(pts) >= 2 and pts[-1].observed_at > pts[0].observed_at:
            d_used = pts[-1].used_fraction - pts[0].used_fraction
            d_days = (pts[-1].observed_at - pts[0].observed_at).total_seconds() / 86400.0
            if d_used > 0:
                burn_per_day = d_used / d_days
                runway_days = max(1.0 - (used_fraction or 0.0), 0.0) / burn_per_day
                projected = now + timedelta(days=runway_days)
    if runway_days is None:
        notes.append("no burn estimate yet: needs >=2 snapshots in this window")

    status = _status(used_fraction, runway_days, days_left, policy)
    return Runway(
        tool=policy.tool, window_id=policy.window_id, unit=Unit.PERCENT, now=now,
        window_start=start, resets_at=reset, used=used_fraction or 0.0, allowance=1.0,
        used_fraction=used_fraction, time_fraction=time_fraction, pace_ratio=pace,
        burn_per_day_avg=burn_per_day, burn_per_day_ema=None, runway_days=runway_days,
        days_left=days_left, projected_exhaustion=projected, status=status,
        source_of_truth="provider_pct", notes=notes,
    )


def compute_runway(events: Iterable[UsageEvent], policy: BudgetPolicy,
                   now: Optional[datetime] = None,
                   quota: Optional[QuotaSnapshot] = None,
                   quota_history: Optional[list[QuotaSnapshot]] = None) -> Runway:
    """Runway from local events, optionally overridden by a provider snapshot.

    If `quota` is given and policy.source_of_truth != "local_sum", the
    provider's used fraction wins (local events only drive the burn rate).
    Percent-based rolling windows are handled by `_percent_runway`.
    """
    now = now or utcnow()
    unit = policy.unit
    notes: list[str] = []

    if unit == Unit.PERCENT:
        if quota is None or quota.used_fraction is None:
            start, reset = window_for(policy, now)
            return Runway(
                tool=policy.tool, window_id=policy.window_id, unit=unit, now=now,
                window_start=start, resets_at=None, used=0.0, allowance=policy.allowance,
                used_fraction=None, time_fraction=None, pace_ratio=None,
                burn_per_day_avg=None, burn_per_day_ema=None, runway_days=None,
                days_left=None, projected_exhaustion=None, status=Status.UNKNOWN,
                source_of_truth=policy.source_of_truth,
                notes=["percent-based budget without provider snapshot: status UNKNOWN "
                       "(Claude Code: wire `token-finops collect-statusline` as statusLine.command)"],
            )
        return _percent_runway(policy, now, quota, quota_history)

    start, reset = window_for(policy, now)
    in_window = [e for e in events if e.ts_utc >= start]
    used = sum(native_amount(e, unit) for e in in_window)

    used_fraction: Optional[float]
    if quota is not None and policy.source_of_truth in ("provider_pct", "hybrid") \
            and quota.used_fraction is not None:
        used_fraction = quota.used_fraction
        if quota.resets_at and quota.resets_at > now:
            reset = quota.resets_at
        notes.append(f"used% from provider ({quota.source})")
        if policy.allowance:
            used = used_fraction * policy.allowance
    elif policy.allowance:
        used_fraction = used / policy.allowance
    else:
        used_fraction = None

    elapsed_days = max((now - start).total_seconds() / 86400.0, 1e-6)
    burn_avg = used / elapsed_days if in_window else None
    burn_ema = ema_daily_burn(daily_buckets(in_window, unit), now)

    days_left = (reset - now).total_seconds() / 86400.0 if reset else None
    window_len = (reset - start).total_seconds() / 86400.0 if reset else None
    time_fraction = (elapsed_days / window_len) if window_len else None
    pace = (used_fraction / time_fraction) if (used_fraction is not None and time_fraction) else None

    runway_days: Optional[float] = None
    projected: Optional[datetime] = None
    if policy.allowance is not None:
        remaining = policy.allowance - used
        # pessimistic: use the larger of avg and ema burn
        burn = max([b for b in (burn_avg, burn_ema) if b], default=None)
        if burn and burn > 0:
            runway_days = max(remaining, 0.0) / burn
            projected = now + timedelta(days=runway_days)
        elif remaining <= 0:
            runway_days = 0.0
            projected = now
        else:
            runway_days = math.inf

    status = _status(used_fraction, runway_days, days_left, policy)

    return Runway(
        tool=policy.tool, window_id=policy.window_id, unit=unit, now=now,
        window_start=start, resets_at=reset, used=used, allowance=policy.allowance,
        used_fraction=used_fraction, time_fraction=time_fraction, pace_ratio=pace,
        burn_per_day_avg=burn_avg, burn_per_day_ema=burn_ema,
        runway_days=runway_days, days_left=days_left, projected_exhaustion=projected,
        status=status, source_of_truth=policy.source_of_truth, notes=notes,
    )


def binding_constraint(runways: Iterable[Runway]) -> Optional[Runway]:
    """Across tools, the runway that will bite first. Never sums units."""
    candidates = [r for r in runways if r.runway_days is not None and r.status != Status.UNLIMITED]
    if not candidates:
        return None
    return min(candidates, key=lambda r: (r.runway_days if r.runway_days is not None else math.inf))
