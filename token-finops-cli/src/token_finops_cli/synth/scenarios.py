"""Named burn profiles shared by every adapter's `build_synthetic_*()`.

Pure, side-effect-free helper functions -- deliberately kept free of any
import from `token_finops_cli.adapters` (which import back into this module),
to avoid a circular import between `synth` and `adapters`.

Scenarios:
- "steady":         even usage across the period (the default; identical to
                    the pre-scenario behaviour every build_synthetic_* had).
- "burst":          quiet, then the last 2 days run at ~5x normal volume.
- "exhausted":      Copilot usage scaled well past its monthly allowance;
                    Claude Code / Codex rate_limits windows pinned to 95-100%.
- "weekend":        zero usage on Saturday/Sunday (UTC).
- "fresh":          first use was yesterday -- usage before day_offset 2 is
                    suppressed regardless of the requested `days`.
- "quiet":          a handful of events with long gaps between them.
- "subagent-heavy": ~60% of Claude Code calls come from sub-agents instead of
                    the main loop (vs. a ~25% baseline).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

KNOWN = ("steady", "burst", "exhausted", "weekend", "fresh", "quiet", "subagent-heavy")


def day_multiplier(scenario: str, day: datetime, day_offset: int) -> float:
    """Scale factor for a day's event count. 0.0 means: skip this day
    entirely. `day_offset` counts back from today (0 = today)."""
    if scenario == "weekend" and day.weekday() >= 5:
        return 0.0
    if scenario == "fresh":
        return 1.0 if day_offset < 2 else 0.0
    if scenario == "burst":
        return 5.0 if day_offset < 2 else 0.6
    if scenario == "quiet":
        return 1.0 if day_offset % 3 == 0 else 0.0
    return 1.0


def scaled_count(scenario: str, day: datetime, day_offset: int, base: int) -> int:
    """`base` events on this day, scaled (and possibly zeroed) by scenario."""
    if base <= 0:
        return 0
    mult = day_multiplier(scenario, day, day_offset)
    if mult <= 0.0:
        return 0
    return max(1, round(base * mult))


def rate_limit_pct(scenario: str, day_offset: int, days: int,
                   base_primary: float, base_secondary: float) -> tuple[float, float]:
    """(primary %, secondary %) for a Claude/Codex rolling-window quota
    snapshot recorded `day_offset` days back out of `days` total. "exhausted"
    pins both windows near the ceiling regardless of the baseline curve."""
    if scenario == "exhausted":
        age = days - day_offset  # 1 = oldest, days = newest
        primary = min(100.0, 95.0 + age * 0.3)
        secondary = min(100.0, 96.0 + age * 0.2)
        return primary, secondary
    return base_primary, base_secondary


def copilot_volume_multiplier(scenario: str) -> float:
    """Scale factor on Copilot's per-event AI-unit cost, so "exhausted" blows past even the
    largest real individual plan (Max, 20,000 AIU -- also the default allowance when none is
    given, see adapters/copilot.py) well before a full month's worth of days has accumulated
    -- robust to however many of the synthetic days the calendar-month window actually
    covers, which depends on the real day of the month a test happens to run on (T-02)."""
    if scenario == "exhausted":
        return 100.0
    return 1.0


def subagent_probability(scenario: str, base: float = 0.25) -> float:
    if scenario == "subagent-heavy":
        return 0.6
    return base


def session_hour_offset(scenario: str, rng: random.Random, max_hours: float) -> float:
    """Hours-ago for one session/task, for generators that place events by a
    random offset into a fixed window (e.g. 'last N days') rather than by
    walking one day at a time."""
    if scenario == "burst":
        # Most sessions land in the most recent 10% of the window.
        return rng.uniform(0, max_hours * 0.1) if rng.random() < 0.8 else rng.uniform(0, max_hours)
    if scenario == "fresh":
        return rng.uniform(0, min(max_hours, 36.0))
    return rng.uniform(0, max_hours)


def adjust_for_weekend(scenario: str, ts: datetime) -> datetime:
    """Nudge a timestamp off a Saturday/Sunday back onto the preceding Friday
    (same time-of-day) when the scenario is 'weekend'."""
    if scenario == "weekend" and ts.weekday() >= 5:
        ts = ts - timedelta(days=ts.weekday() - 4)
    return ts


def session_count_multiplier(scenario: str) -> float:
    """For session/task-count generators (Hermes, OpenCode, Cline) that have
    no per-day loop: scale the total count instead."""
    if scenario == "quiet":
        return 0.35
    if scenario == "fresh":
        return 0.25
    return 1.0
