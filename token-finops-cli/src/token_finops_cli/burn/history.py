"""Historical stats: daily per-tool aggregates persisted outside the tools' own stores.

Why: Claude Code prunes transcripts after ~30 days, Codex archives rollouts, Copilot's
session-store can be reset — the telemetry `report` reads is a sliding window. `history
record` folds today's view into `~/.token-finops/history.jsonl` (one line per tool per UTC
day, upserted, live data always wins), so `burn --by month --since all` can look back
further than any single tool remembers. Run it from the same timer that refreshes `status`.

Line shape (schema_version 1):
{"schema_version": 1, "tool": "claude_code", "day": "2026-09-11", "calls": 84, "input": 12,
 "output": 4020, "cache_read": 9100000, "cache_write": 210000, "usd": 12.34,
 "by_model": {"claude-sonnet-5": 3.21, ...}, "recorded_at": "2026-09-11T14:02:00+00:00"}
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from ..core.model import UsageEvent

SCHEMA_VERSION = 1
HISTORY_FILE = os.path.expanduser("~/.token-finops/history.jsonl")
FIELDS = ("calls", "input", "output", "cache_read", "cache_write")


def daily_aggregates(events: Iterable[UsageEvent], tool: str) -> dict[str, dict]:
    """{day: record} from live events (UTC days)."""
    days: dict[str, dict] = {}
    for e in events:
        d = e.ts_utc.astimezone(timezone.utc).date().isoformat()
        rec = days.setdefault(d, {"schema_version": SCHEMA_VERSION, "tool": tool, "day": d, "calls": 0, "input": 0,
                                  "output": 0, "cache_read": 0, "cache_write": 0, "usd": 0.0, "by_model": {}})
        rec["calls"] += 1
        rec["input"] += e.input_tokens
        rec["output"] += e.output_tokens
        rec["cache_read"] += e.cache_read_tokens
        rec["cache_write"] += e.cache_write_tokens
        if e.usd_estimate is not None:
            rec["usd"] += e.usd_estimate
            rec["by_model"][e.model_norm] = rec["by_model"].get(e.model_norm, 0.0) + e.usd_estimate
    return days


def read_history(path: str = HISTORY_FILE) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("schema_version") == SCHEMA_VERSION and "tool" in rec and "day" in rec:
                    out.append(rec)
    except OSError:
        return []
    return out


def upsert(records: Iterable[dict], path: str = HISTORY_FILE, now: Optional[datetime] = None) -> int:
    """Merge records into the file keyed by (tool, day). Returns the number of lines written."""
    now = now or datetime.now(timezone.utc)
    merged = {(r["tool"], r["day"]): r for r in read_history(path)}
    for r in records:
        r = dict(r, recorded_at=now.isoformat(timespec="seconds"))
        merged[(r["tool"], r["day"])] = r
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for key in sorted(merged):
            fh.write(json.dumps(merged[key], default=str) + "\n")
    os.replace(tmp, path)
    return len(merged)


def merge_live(live: dict[str, dict], history: Iterable[dict], tool: str) -> dict[str, dict]:
    """Live days win; history fills in days the tool has already forgotten."""
    out = {r["day"]: r for r in history if r.get("tool") == tool}
    out.update(live)
    return out


def period_key(day: str, by: str) -> str:
    d = date.fromisoformat(day)
    if by == "day":
        return day
    if by == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    if by == "month":
        return f"{d.year}-{d.month:02d}"
    raise ValueError(by)


def period_bounds(key: str, by: str) -> tuple[date, date]:
    """Calendar [start, end] (inclusive) of the period named `key`."""
    if by == "day":
        d = date.fromisoformat(key)
        return d, d
    if by == "week":
        y_str, w_str = key.split("-W")
        y, w = int(y_str), int(w_str)
        return date.fromisocalendar(y, w, 1), date.fromisocalendar(y, w, 7)
    y, m = (int(x) for x in key.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return first, nxt - timedelta(days=1)


def period_days(key: str, by: str) -> int:
    """Calendar length of the period (full week/month), for reference — NOT what run-rate
    normalisation should divide by when the reporting window only covers part of this period
    (the first/last period of a `--since`/`--by` window); see `period_window_days` for that."""
    start, end = period_bounds(key, by)
    return (end - start).days + 1


def period_window_days(key: str, by: str, first_day: str, last_day: str) -> tuple[int, bool]:
    """Days of period `key` that actually fall inside [first_day, last_day] (inclusive) —
    the real reporting window, not the full calendar period. Returns
    (actual_days, is_partial) where is_partial is True when actual_days is fewer than the
    period's full calendar length (the period is only partly covered by the window, typically
    at its first or last edge)."""
    start, end = period_bounds(key, by)
    first = date.fromisoformat(first_day)
    last = date.fromisoformat(last_day)
    actual = (min(end, last) - max(start, first)).days + 1
    cal_days = (end - start).days + 1
    return actual, actual < cal_days


def group(days: dict[str, dict], by: str) -> dict[str, dict]:
    """Aggregate `days` (day -> record) into periods. Each group also carries `period_days`
    (the days of the period actually inside the [min(days), max(days)] window — the real
    reporting window, not the full calendar period) and `partial` (True when that's fewer than
    the calendar length), so callers can normalise run-rates by what was actually observed
    instead of overstating the denominator at the edges of the window."""
    out: dict[str, dict] = {}
    for day, rec in days.items():
        k = period_key(day, by)
        g = out.setdefault(k, {"period": k, "days": 0, "calls": 0, "input": 0, "output": 0, "cache_read": 0,
                               "cache_write": 0, "usd": 0.0, "by_model": defaultdict(float)})
        g["days"] += 1
        for f in FIELDS:
            g[f] += rec.get(f, 0)
        g["usd"] += rec.get("usd", 0.0)
        for m, v in (rec.get("by_model") or {}).items():
            g["by_model"][m] += v
    if days:
        first_day, last_day = min(days), max(days)
    for k, g in out.items():
        g["by_model"] = dict(g["by_model"])
        g["tokens"] = g["input"] + g["output"] + g["cache_read"] + g["cache_write"]
        g["period_days"], g["partial"] = period_window_days(k, by, first_day, last_day)
    return dict(sorted(out.items()))


def cutoff_day(since: Optional[timedelta], now: Optional[datetime] = None) -> Optional[str]:
    if since is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - since).date().isoformat()
