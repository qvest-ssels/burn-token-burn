"""Text rendering shared by the CLI subcommands. Plain ASCII on purpose
(the original tool learned the hard way that block glyphs vanish in some
terminal fonts)."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Iterable, Optional

from .core.model import Runway, Status, Unit, UsageEvent


def fmt_tokens(n: float) -> str:
    n = float(n)
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}k"
    return f"{int(n)}"


def fmt_usd(x: Optional[float]) -> str:
    return "n/a" if x is None else f"${x:,.2f}"


def fmt_days(d: Optional[float]) -> str:
    if d is None:
        return "n/a"
    if math.isinf(d):
        return "inf"
    if d < 1:
        return f"{d * 24:.1f}h"
    return f"{d:.1f}d"


def progress_bar(fraction: Optional[float], width: int = 30) -> str:
    if fraction is None:
        return "[" + "?" * width + "]   n/a"
    f = max(0.0, min(1.0, fraction))
    filled = round(width * f)
    return f"[{'#' * filled}{'-' * (width - filled)}] {f * 100:5.1f}%"


def unit_label(unit: Unit) -> str:
    return {Unit.AIU: "AI units", Unit.USD: "USD", Unit.REQUESTS: "requests",
            Unit.PERCENT: "%", Unit.TOKENS: "tokens", Unit.MINUTES: "min"}[unit]


def fmt_amount(x: float, unit: Unit) -> str:
    if unit == Unit.USD:
        return f"${x:,.2f}"
    if unit == Unit.PERCENT:
        return f"{x * 100:.0f}%"
    if unit == Unit.TOKENS:
        return fmt_tokens(x)
    return f"{x:,.1f}"


def render_runway(r: Runway, display_name: str) -> list[str]:
    lines = [f"{display_name} — window: {r.window_id}"
             + (f" (resets {r.resets_at:%Y-%m-%d %H:%M} UTC)" if r.resets_at else " (rolling)")]
    lines.append(f"  budget:   {progress_bar(r.used_fraction)}")
    if r.unit == Unit.PERCENT:
        if r.used_fraction is not None:
            lines.append(f"  used:     {r.used_fraction * 100:.0f}% of the {r.window_id} window")
    elif r.allowance is not None:
        lines.append(f"  used:     {fmt_amount(r.used, r.unit)} / {fmt_amount(r.allowance, r.unit)} {unit_label(r.unit)}")
    else:
        lines.append(f"  used:     {fmt_amount(r.used, r.unit)} {unit_label(r.unit)} (no allowance set)")
    if r.time_fraction is not None:
        lines.append(f"  window:   {progress_bar(r.time_fraction)} elapsed")
    if r.pace_ratio is not None:
        verdict = "on pace" if r.pace_ratio <= 1.0 else f"{r.pace_ratio:.2f}x too fast"
        lines.append(f"  pace:     {r.pace_ratio:.2f} ({verdict})")
    if r.burn_per_day_avg is not None:
        if r.unit == Unit.PERCENT:
            lines.append(f"  burn:     {r.burn_per_day_avg * 100 / 24:.1f}% per hour (from snapshots)")
        else:
            ema = f", EMA {fmt_amount(r.burn_per_day_ema, r.unit)}" if r.burn_per_day_ema else ""
            lines.append(f"  burn:     {fmt_amount(r.burn_per_day_avg, r.unit)} {unit_label(r.unit)}/day avg{ema}")
    if r.runway_days is not None:
        vs = f" vs {fmt_days(r.days_left)} left" if r.days_left is not None else ""
        lines.append(f"  runway:   {fmt_days(r.runway_days)}{vs} -> {r.status.value}")
    else:
        lines.append(f"  runway:   n/a -> {r.status.value}")
    for n in r.notes:
        lines.append(f"  note:     {n}")
    return lines


def compact_line(r: Runway, display_name: str) -> str:
    icon = {Status.OK: "OK", Status.WARN: "WARN", Status.CRITICAL: "CRIT",
            Status.EXHAUSTED: "OUT", Status.UNLIMITED: "inf", Status.UNKNOWN: "?"}[r.status]
    bar = progress_bar(r.used_fraction, width=20)
    rw = fmt_days(r.runway_days) if r.runway_days is not None else "n/a"
    return f"{display_name:<18} {bar}  runway {rw:>6}  {icon}"


# --------------------------------------------------------------------------- #
# Usage summaries
# --------------------------------------------------------------------------- #
def summarize(events: Iterable[UsageEvent]) -> dict:
    s = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
         "reasoning": 0, "usd": 0.0, "usd_known": 0, "sessions": set(), "agents": set()}
    for e in events:
        s["calls"] += 1
        s["input"] += e.input_tokens
        s["output"] += e.output_tokens
        s["cache_read"] += e.cache_read_tokens
        s["cache_write"] += e.cache_write_tokens
        s["reasoning"] += e.reasoning_tokens
        if e.usd_estimate is not None:
            s["usd"] += e.usd_estimate
            s["usd_known"] += 1
        s["sessions"].add(e.session_id)
        if e.agent_id:
            s["agents"].add(e.agent_id)
    return s


def render_summary(title: str, events: list[UsageEvent]) -> list[str]:
    s = summarize(events)
    total = s["input"] + s["output"] + s["cache_read"] + s["cache_write"]
    lines = [f"{title}:"]
    lines.append(f"  calls:            {s['calls']}  (sessions {len(s['sessions'])}, sub-agents {len(s['agents'])})")
    lines.append(f"  input tokens:     {fmt_tokens(s['input'])}")
    lines.append(f"  output tokens:    {fmt_tokens(s['output'])}")
    lines.append(f"  cache read:       {fmt_tokens(s['cache_read'])}")
    lines.append(f"  cache write:      {fmt_tokens(s['cache_write'])}")
    if s["reasoning"]:
        lines.append(f"  reasoning tokens: {fmt_tokens(s['reasoning'])}")
    lines.append(f"  total tokens:     {fmt_tokens(total)}")
    if s["calls"]:
        lines.append(f"  tokens/call:      {fmt_tokens(total / s['calls'])}")
    if s["usd_known"]:
        cov = "" if s["usd_known"] == s["calls"] else f"  (priced {s['usd_known']}/{s['calls']} calls)"
        lines.append(f"  API-equivalent:   {fmt_usd(s['usd'])}{cov}")
    return lines


def by_model(events: Iterable[UsageEvent]) -> list[tuple[str, dict]]:
    groups: dict[str, list[UsageEvent]] = defaultdict(list)
    for e in events:
        groups[e.model_norm or "(unknown)"].append(e)
    rows = [(m, summarize(evs)) for m, evs in groups.items()]
    rows.sort(key=lambda kv: -kv[1]["usd"])
    return rows


def render_by_model(events: list[UsageEvent]) -> list[str]:
    rows = by_model(events)
    total_usd = sum(s["usd"] for _, s in rows) or 1.0
    lines = [f"  {'model':<24} {'calls':>6} {'in':>8} {'out':>8} {'cache r/w':>16} {'API-eq $':>10} {'share':>6}"]
    for m, s in rows:
        lines.append(
            f"  {m:<24} {s['calls']:>6} {fmt_tokens(s['input']):>8} {fmt_tokens(s['output']):>8} "
            f"{fmt_tokens(s['cache_read']) + '/' + fmt_tokens(s['cache_write']):>16} "
            f"{s['usd']:>10.2f} {s['usd'] / total_usd * 100:>5.0f}%"
        )
    return lines


def render_sessions_table(events: list[UsageEvent], limit: int = 20) -> list[str]:
    groups: dict[str, list[UsageEvent]] = defaultdict(list)
    for e in events:
        groups[e.session_id or "(none)"].append(e)
    rows = []
    for sid, evs in groups.items():
        s = summarize(evs)
        last = max(e.ts_utc for e in evs)
        rows.append((last, sid, s))
    rows.sort(reverse=True)
    lines = [f"  {'session':<38} {'calls':>5} {'tokens':>9} {'API-eq $':>9}  last activity"]
    for last, sid, s in rows[:limit]:
        tot = s["input"] + s["output"] + s["cache_read"] + s["cache_write"]
        lines.append(f"  {sid[:36]:<38} {s['calls']:>5} {fmt_tokens(tot):>9} {s['usd']:>9.2f}  {last:%Y-%m-%d %H:%M}")
    return lines


def fmt_dt(dt: Optional[datetime]) -> str:
    return "n/a" if dt is None else dt.strftime("%Y-%m-%d %H:%M UTC")
