"""Claude Code adapter.

Source: `~/.claude/projects/<project>/<session>.jsonl` plus
`<session>/subagents/agent-*.jsonl` (sub-agent transcripts, each with its own
model — e.g. a Haiku agent polishing markdown while the main loop runs Fable).

Each `type == "assistant"` line carries `message.usage`; Claude Code writes
one line per content block, so the same API response appears several times.
Dedup key: `(message.id, requestId)` — on this repository's own session that
collapses 371 lines to 197 real API calls (~1.9x over-count otherwise).

Budget: Anthropic subscriptions expose only opaque percentages of a rolling
5-hour window and a rolling 7-day window. Local transcripts therefore give
you *what you did* (tokens, models, sub-agents, USD-equivalent), while the
authoritative *how much is left* comes from a QuotaSnapshot written by the
status-line collector (`token-finops collect-statusline`) into
`~/.token-finops/quota.json`.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Unit, UsageEvent
from ..core.pricing import estimate_usd
from .base import BaseAdapter, register

QUOTA_FILE = os.path.expanduser("~/.token-finops/quota.json")
QUOTA_HISTORY_FILE = os.path.expanduser("~/.token-finops/quota_history.jsonl")


def _parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_transcript(path: str, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
    """Yield deduplicated UsageEvents from one JSONL transcript."""
    seen: set[tuple] = set()
    fname = os.path.basename(path)
    file_agent = fname[len("agent-"):-len(".jsonl")] if fname.startswith("agent-") else ""
    session_from_path = os.path.basename(os.path.dirname(path)) if file_agent else fname[:-len(".jsonl")]
    if file_agent and os.path.basename(os.path.dirname(path)) == "subagents":
        session_from_path = os.path.basename(os.path.dirname(os.path.dirname(path)))

    # One API response is spread over several lines (one per content block).
    # Collect them, take usage from the first line and tool_use names from all.
    events: dict[tuple, UsageEvent] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("{"):
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") != "assistant":
                continue
            msg = e.get("message") or {}
            usage = msg.get("usage")
            if not usage:
                continue
            key = (msg.get("id"), e.get("requestId")) if msg.get("id") else (e.get("uuid"), None)
            tools = [c.get("name") for c in (msg.get("content") or [])
                     if isinstance(c, dict) and c.get("type") == "tool_use"]
            if key in seen:
                ev = events.get(key)
                if ev is not None and tools:
                    ev.tags["tools"].extend(tools)
                    ev.tags["first_tool"] = ev.tags["first_tool"] or tools[0]
                continue
            seen.add(key)
            try:
                ts = _parse_ts(e.get("timestamp", ""))
            except ValueError:
                continue
            if since is not None and ts < since:
                continue
            cc = usage.get("cache_creation") or {}
            cw_total = int(usage.get("cache_creation_input_tokens") or 0)
            cw_1h = int(cc.get("ephemeral_1h_input_tokens") or 0)
            model = str(msg.get("model") or "")
            inp = int(usage.get("input_tokens") or 0)
            out = int(usage.get("output_tokens") or 0)
            cr = int(usage.get("cache_read_input_tokens") or 0)
            events[key] = UsageEvent(
                tags={"first_tool": tools[0] if tools else "", "tools": list(tools)},
                ts_utc=ts,
                tool="claude_code",
                model_raw=model,
                input_tokens=inp,
                output_tokens=out,
                cache_read_tokens=cr,
                cache_write_tokens=cw_total,
                reasoning_tokens=0,
                session_id=str(e.get("sessionId") or session_from_path),
                agent_id=str(e.get("agentId") or file_agent),
                parent_id=str(e.get("parentUuid") or ""),
                initiator="agent" if (e.get("isSidechain") or file_agent) else "user",
                usd_estimate=estimate_usd(model, inp, out, cr, cw_total, cw_1h),
                cwd=str(e.get("cwd") or ""),
                event_id=f"{key[0]}:{key[1]}",
            )
    yield from events.values()


@register
class ClaudeCodeAdapter(BaseAdapter):
    tool = "claude_code"
    display_name = "Claude Code"

    def default_root(self) -> str:
        cfg = os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")
        return os.path.join(cfg, "projects")

    def transcript_paths(self) -> list[str]:
        return sorted(glob.glob(os.path.join(self.root, "**", "*.jsonl"), recursive=True))

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        for path in self.transcript_paths():
            yield from parse_transcript(path, since)

    @staticmethod
    def _snapshot(data: dict, window: str = "five_hour") -> Optional[QuotaSnapshot]:
        rl = (data.get("rate_limits") or {}).get(window) or {}
        if not rl or rl.get("used_percentage") is None:
            return None
        resets = rl.get("resets_at")
        if isinstance(resets, str):
            try:
                resets_dt = _parse_ts(resets)
            except ValueError:
                resets_dt = None
        elif isinstance(resets, (int, float)):
            resets_dt = datetime.fromtimestamp(resets, tz=timezone.utc)
        else:
            resets_dt = None
        return QuotaSnapshot(
            tool="claude_code", window_id="5h" if window == "five_hour" else "7d",
            observed_at=_parse_ts(data.get("observed_at") or datetime.now(timezone.utc).isoformat()),
            used_fraction=float(rl["used_percentage"]) / 100.0,
            resets_at=resets_dt, source="claude_statusline",
        )

    def quota(self, window: str = "five_hour") -> Optional[QuotaSnapshot]:
        """Latest snapshot written by the status-line collector, if any."""
        try:
            with open(QUOTA_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        return self._snapshot(data, window)

    def quota_history(self, window: str = "five_hour", limit: int = 500) -> list[QuotaSnapshot]:
        """All snapshots the collector appended (newest last)."""
        out: list[QuotaSnapshot] = []
        try:
            with open(QUOTA_HISTORY_FILE, encoding="utf-8") as fh:
                lines = fh.readlines()[-limit:]
        except OSError:
            return out
        for line in lines:
            try:
                snap = self._snapshot(json.loads(line), window)
            except ValueError:
                continue
            if snap:
                out.append(snap)
        return out

    def default_policy(self, allowance: Optional[float] = None) -> BudgetPolicy:
        # Percent-based rolling 5h window; allowance 1.0 == 100 %.
        return BudgetPolicy(
            tool=self.tool, window_id="5h", unit=Unit.PERCENT, cycle=CycleKind.ROLLING,
            window_length=timedelta(hours=5), allowance=1.0 if allowance is None else allowance,
            source_of_truth="provider_pct",
        )


# --------------------------------------------------------------------------- #
# 5-hour billing blocks (ccusage algorithm): a block starts at the first
# event's hour (floored) and ends 5 h later; a new block starts when an event
# falls after the block end or after a gap >= 5 h.
# --------------------------------------------------------------------------- #
def five_hour_blocks(events: list[UsageEvent], length: timedelta = timedelta(hours=5)) -> list[dict]:
    blocks: list[dict] = []
    cur: Optional[dict] = None
    last_ts: Optional[datetime] = None
    for ev in sorted(events, key=lambda e: e.ts_utc):
        if cur is None or ev.ts_utc >= cur["end"] or (last_ts and ev.ts_utc - last_ts >= length):
            start = ev.ts_utc.replace(minute=0, second=0, microsecond=0)
            cur = {"start": start, "end": start + length, "events": [], "usd": 0.0,
                   "tokens": 0, "models": {}}
            blocks.append(cur)
        cur["events"].append(ev)
        cur["usd"] += ev.usd_estimate or 0.0
        cur["tokens"] += ev.total_tokens
        cur["models"][ev.model_norm] = cur["models"].get(ev.model_norm, 0) + 1
        last_ts = ev.ts_utc
    return blocks
