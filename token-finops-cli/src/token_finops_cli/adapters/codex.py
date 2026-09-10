"""OpenAI Codex CLI adapter.

Source: `${CODEX_HOME:-~/.codex}/sessions/YYYY/MM/DD/rollout-*.jsonl` plus
`archived_sessions/**` (same JSONL shape, rolled over by the CLI).

Each rollout file is a JSONL transcript of one Codex session:
- `type == "session_meta"` carries `payload.id` (session id) and `payload.cwd`.
- `type == "turn_context"` carries `payload.model` (current model; may change
  mid-session if the user switches models).
- `type == "event_msg"` with `payload.type == "token_count"` carries
  `payload.info.total_token_usage` — **cumulative** counters for the whole
  session (`input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`,
  `output_tokens`, `reasoning_output_tokens`, `total_tokens`). We emit the
  *delta* against the previous cumulative snapshot for that session. Codex
  writes duplicate token_count lines with an unchanged total (e.g. a
  heartbeat) — those produce a zero/negative delta and are skipped. If
  `total_token_usage` is absent, fall back to `last_token_usage` (per-turn,
  already a delta) when present.

Dedup key: `event_id = f"{session_id}:{line_no}"` — one event per line that
produces a positive delta; the session id plus line number is stable and
unique because a rollout file is append-only.

`input_tokens` from Codex includes cached tokens, so
`input = input_tokens - cached_input_tokens`; `cache_read_tokens =
cached_input_tokens`; `cache_write_tokens = cache_write_input_tokens`.
`reasoning_output_tokens` is a subset of `output_tokens`
(`reasoning_is_subset_of_output=True`).

Budget model: ChatGPT/Codex subscriptions expose only opaque percentages of a
rolling 5-hour window (`primary`) and a rolling 7-day window (`secondary`),
reported in `payload.rate_limits` on `token_count` events. `quota()` returns
the primary ("5h") snapshot from the newest rollout file; `quotas()` returns
both. `default_policy()` therefore uses `Unit.PERCENT` /
`CycleKind.ROLLING` with `source_of_truth="provider_pct"` — local token sums
are "what you did", not "how much is left".
"""
from __future__ import annotations

import glob
import json
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Unit, UsageEvent
from ..core.pricing import estimate_usd
from .base import BaseAdapter, register


def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _int(d: dict, *keys: str) -> int:
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0
    return 0


def parse_rollout(path: str, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
    """Yield deduplicated, delta UsageEvents from one rollout-*.jsonl file."""
    fname = os.path.basename(path)
    session_id = fname
    cwd = ""
    model = "codex"
    prev_totals: Optional[dict] = None

    try:
        # errors="replace"/OSError: a half-written or unreadable rollout (or a
        # directory named rollout-*.jsonl) must not abort the whole scan.
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line_no, line in enumerate(fh):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            rtype = rec.get("type")
            payload = rec.get("payload")
            if not isinstance(payload, dict):
                payload = {}  # drifted/garbage shape: treat as "no payload"

            if rtype == "session_meta":
                session_id = str(payload.get("id") or session_id)
                cwd = str(payload.get("cwd") or cwd)
                continue
            if rtype == "turn_context":
                model = str(payload.get("model") or model)
                continue
            if rtype != "event_msg" or payload.get("type") != "token_count":
                continue

            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            totals = info.get("total_token_usage")
            delta_src = None
            if isinstance(totals, dict):
                if prev_totals is None:
                    delta = {
                        k: _int(totals, k)
                        for k in (
                            "input_tokens", "cached_input_tokens",
                            "cache_write_input_tokens", "output_tokens",
                            "reasoning_output_tokens",
                        )
                    }
                else:
                    delta = {
                        k: _int(totals, k) - _int(prev_totals, k)
                        for k in (
                            "input_tokens", "cached_input_tokens",
                            "cache_write_input_tokens", "output_tokens",
                            "reasoning_output_tokens",
                        )
                    }
                prev_totals = totals
                delta_src = delta
            else:
                last = info.get("last_token_usage")
                if isinstance(last, dict):
                    delta_src = {
                        "input_tokens": _int(last, "input_tokens"),
                        "cached_input_tokens": _int(last, "cached_input_tokens"),
                        "cache_write_input_tokens": _int(last, "cache_write_input_tokens"),
                        "output_tokens": _int(last, "output_tokens"),
                        "reasoning_output_tokens": _int(last, "reasoning_output_tokens"),
                    }

            if delta_src is None:
                continue

            total_delta = (
                delta_src["input_tokens"] + delta_src["output_tokens"]
                + delta_src["cached_input_tokens"] + delta_src["cache_write_input_tokens"]
            )
            if total_delta <= 0:
                continue

            ts = _parse_ts(rec.get("timestamp")) or _parse_ts(payload.get("timestamp"))
            if ts is None:
                ts = datetime.now(timezone.utc)
            if since is not None and ts < since:
                continue

            cached = delta_src["cached_input_tokens"]
            inp_total = delta_src["input_tokens"]
            inp = max(0, inp_total - cached)
            out = delta_src["output_tokens"]
            cw = delta_src["cache_write_input_tokens"]
            reasoning = delta_src["reasoning_output_tokens"]

            yield UsageEvent(
                ts_utc=ts,
                tool="codex",
                model_raw=model,
                input_tokens=inp,
                output_tokens=out,
                cache_read_tokens=cached,
                cache_write_tokens=cw,
                reasoning_tokens=reasoning,
                reasoning_is_subset_of_output=True,
                session_id=session_id,
                initiator="user",
                usd_estimate=estimate_usd(model, inp, out, cached, cw),
                cwd=cwd,
                event_id=f"{session_id}:{line_no}",
            )


def _rate_limits_from_line(rec: dict) -> Optional[dict]:
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return None
    if rec.get("type") != "event_msg" or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    rl = info.get("rate_limits")
    return rl if isinstance(rl, dict) and rl else None


def _snapshot_from_window(win: dict, window_id: str, observed_at: datetime) -> Optional[QuotaSnapshot]:
    if not isinstance(win, dict) or not win:
        return None
    try:
        pct = float(win["used_percent"]) if win.get("used_percent") is not None else None
    except (TypeError, ValueError):
        pct = None
    resets = win.get("resets_at")
    resets_at = None
    if isinstance(resets, (int, float)) and not isinstance(resets, bool):
        try:
            resets_at = datetime.fromtimestamp(resets, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            resets_at = None
    elif isinstance(resets, str):
        resets_at = _parse_ts(resets)
    return QuotaSnapshot(
        tool="codex",
        window_id=window_id,
        observed_at=observed_at,
        used_fraction=(pct / 100.0) if pct is not None else None,
        resets_at=resets_at,
        source="codex_rollout",
    )


@register
class CodexAdapter(BaseAdapter):
    tool = "codex"
    display_name = "OpenAI Codex CLI"

    def default_root(self) -> str:
        return os.environ.get("CODEX_HOME", "~/.codex")

    def rollout_paths(self) -> list[str]:
        paths = []
        for sub in ("sessions", "archived_sessions"):
            paths.extend(glob.glob(os.path.join(self.root, sub, "**", "rollout-*.jsonl"),
                                    recursive=True))
        return sorted(paths)

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        for path in self.rollout_paths():
            yield from parse_rollout(path, since)

    def _newest_rollout(self) -> Optional[str]:
        paths = self.rollout_paths()
        if not paths:
            return None
        return max(paths, key=lambda p: os.path.getmtime(p))

    def _last_rate_limits(self) -> Optional[tuple[dict, datetime]]:
        """Rate limits from the LAST token_count line (with rate_limits) in the
        newest rollout file, plus that line's timestamp (observed_at)."""
        path = self._newest_rollout()
        if path is None:
            return None
        last_rl = None
        last_ts = None
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            return None
        with fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                rl = _rate_limits_from_line(rec)
                if rl is not None:
                    last_rl = rl
                    last_ts = _parse_ts(rec.get("timestamp")) or last_ts
        if last_rl is None:
            return None
        return last_rl, (last_ts or datetime.now(timezone.utc))

    def quotas(self) -> tuple[Optional[QuotaSnapshot], Optional[QuotaSnapshot]]:
        """Return (primary "5h", secondary "7d") QuotaSnapshots from the
        newest rollout's last rate_limits payload."""
        found = self._last_rate_limits()
        if found is None:
            return None, None
        rl, observed_at = found
        primary = _snapshot_from_window(rl.get("primary"), "5h", observed_at)
        secondary = _snapshot_from_window(rl.get("secondary"), "7d", observed_at)
        return primary, secondary

    def quota(self) -> Optional[QuotaSnapshot]:
        primary, _secondary = self.quotas()
        return primary

    def default_policy(self, allowance: Optional[float] = None) -> BudgetPolicy:
        return BudgetPolicy(
            tool=self.tool, window_id="5h", unit=Unit.PERCENT, cycle=CycleKind.ROLLING,
            window_length=timedelta(hours=5), allowance=1.0 if allowance is None else allowance,
            source_of_truth="provider_pct",
        )


# --------------------------------------------------------------------------- #
# Synthetic fixture builder for tests/demos.
# --------------------------------------------------------------------------- #
def build_synthetic_codex(root_dir: str, days: int = 3, sessions_per_day: int = 2,
                          seed: int = 1, scenario: str = "steady",
                          now: Optional[datetime] = None) -> int:
    """Write realistic rollout JSONL fixtures under
    `root_dir/sessions/YYYY/MM/DD/rollout-*.jsonl`. Returns the number of
    distinct positive-delta token_count events written across all files.

    `scenario` (see `synth.scenarios`) shapes per-day session count and, for
    "exhausted", pins the primary/secondary rate_limits windows near 95-100%
    instead of the baseline ramp. "steady" (the default) reproduces the exact
    pre-scenario output for the same seed/days/sessions_per_day."""
    from ..synth.scenarios import rate_limit_pct, scaled_count

    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    models = ["gpt-5", "gpt-5-mini", "o4-mini"]
    total_events = 0

    for day_offset in range(days):
        day = now - timedelta(days=day_offset)
        day_sessions = (sessions_per_day if scenario == "steady"
                        else scaled_count(scenario, day, day_offset, sessions_per_day))
        if day_sessions <= 0:
            continue
        day_dir = os.path.join(root_dir, "sessions", f"{day.year:04d}", f"{day.month:02d}",
                                f"{day.day:02d}")
        os.makedirs(day_dir, exist_ok=True)
        for s in range(day_sessions):
            session_id = f"sess-{day_offset}-{s}-{rng.randint(1000, 9999)}"
            model = models[(day_offset + s) % len(models)]
            path = os.path.join(day_dir, f"rollout-{session_id}.jsonl")
            base_ts = day.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(minutes=s * 5)

            lines = []
            lines.append({
                "type": "session_meta",
                "timestamp": base_ts.isoformat(),
                "payload": {"id": session_id, "cwd": f"/home/user/project{s}"},
            })
            lines.append({
                "type": "turn_context",
                "timestamp": base_ts.isoformat(),
                "payload": {"model": model},
            })

            cum = {"input_tokens": 0, "cached_input_tokens": 0,
                   "cache_write_input_tokens": 0, "output_tokens": 0,
                   "reasoning_output_tokens": 0}
            n_turns = rng.randint(3, 5)
            dup_index = rng.randint(0, n_turns - 1)
            turn_records = []
            for t in range(n_turns):
                cum["input_tokens"] += rng.randint(200, 2000)
                cum["cached_input_tokens"] += rng.randint(0, 500)
                cum["cache_write_input_tokens"] += rng.randint(0, 300)
                cum["output_tokens"] += rng.randint(100, 1000)
                cum["reasoning_output_tokens"] += rng.randint(0, 200)
                cum["total_tokens"] = (cum["input_tokens"] + cum["output_tokens"])
                ts = base_ts + timedelta(minutes=t * 2)
                base_primary = min(95.0, 5.0 + t * 12.5 + day_offset * 3)
                base_secondary = min(90.0, 2.0 + t * 5.0 + day_offset * 2)
                used_pct_primary, used_pct_secondary = rate_limit_pct(
                    scenario, day_offset, days, base_primary, base_secondary)
                resets_primary = ts + timedelta(minutes=300)
                resets_secondary = ts + timedelta(minutes=10080)
                rec = {
                    "type": "event_msg",
                    "timestamp": ts.isoformat(),
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": dict(cum),
                            "model_context_window": 272000,
                            "rate_limits": {
                                "primary": {
                                    "used_percent": used_pct_primary,
                                    "window_minutes": 300,
                                    "resets_at": int(resets_primary.timestamp()),
                                },
                                "secondary": {
                                    "used_percent": used_pct_secondary,
                                    "window_minutes": 10080,
                                    "resets_at": int(resets_secondary.timestamp()),
                                },
                                "plan_type": "plus",
                            },
                        },
                    },
                }
                turn_records.append(rec)
                total_events += 1

            # Duplicate one token_count line (unchanged cumulative totals) to
            # exercise dedup — insert a copy right after its original.
            out_records = []
            for i, rec in enumerate(turn_records):
                out_records.append(rec)
                if i == dup_index:
                    out_records.append(json.loads(json.dumps(rec)))  # exact duplicate

            lines.extend(out_records)

            with open(path, "w", encoding="utf-8") as fh:
                for rec in lines:
                    fh.write(json.dumps(rec) + "\n")
            # A real ~/.codex has file mtimes matching the session date; this
            # generator writes newest-day-first, so stamp each rollout with its
            # own session time. `quota()` picks the *newest* rollout by mtime
            # and would otherwise report the oldest day's rate_limits.
            last_ts = (turn_records[-1]["timestamp"] if turn_records else base_ts.isoformat())
            stamp = (_parse_ts(last_ts) or base_ts).timestamp()
            os.utime(path, (stamp, stamp))

    return total_events
