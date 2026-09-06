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


# --------------------------------------------------------------------------- #
# Synthetic fixture builder (for tests/demos)
# --------------------------------------------------------------------------- #
def _synthetic_transcript_line(ts: datetime, msg_id: str, req_id: str, *, model: str,
                               tool: Optional[str], session: str, inp: int, out: int,
                               cr: int, cw: int, agent: str = "", block_suffix: str = "") -> str:
    """One line of a Claude Code transcript (see `parse_transcript`'s
    docstring for the on-disk shape). Used only by
    `build_synthetic_claude_code`."""
    content = ([{"type": "tool_use", "id": f"toolu_{msg_id}{block_suffix}", "name": tool, "input": {}}]
              if tool else [{"type": "text", "text": "synthetic"}])
    e = {
        "type": "assistant",
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "sessionId": session,
        "requestId": req_id,
        "uuid": f"u-{msg_id}{block_suffix}",
        "isSidechain": bool(agent),
        "cwd": "/home/demo/project",
        "message": {
            "id": msg_id, "model": model, "role": "assistant", "content": content,
            "usage": {
                "input_tokens": inp, "output_tokens": out,
                "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw,
                "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": cw},
            },
        },
    }
    if agent:
        e["agentId"] = agent
    return json.dumps(e)


def build_synthetic_claude_code(config_dir: str, days: int = 14, seed: int = 42,
                                scenario: str = "steady", now: Optional[datetime] = None,
                                events_per_day: int = 6) -> dict:
    """Write a synthetic `${CLAUDE_CONFIG_DIR}/projects/<project>/<session>.jsonl`
    tree (plus `<session>/subagents/agent-*.jsonl`) under `config_dir`, and a
    status-line `<parent of config_dir>/.token-finops/quota.json` +
    `quota_history.jsonl` pair (what `token-finops collect-statusline`
    normally writes -- see the QUOTA_FILE/QUOTA_HISTORY_FILE caveat in
    `synth.env`).

    One project directory, one session per active day. Each API response is
    written as two duplicated content-block lines (mirrors what Claude Code
    actually writes -- one line per content block of the same response) so
    parsers exercise dedup. `scenario` (see `synth.scenarios`) shapes per-day
    call volume, the main-loop/sub-agent split ("subagent-heavy" raises
    sub-agent share to ~60% vs. a 25% baseline), and the rolling-window quota
    snapshots ("exhausted" pins 5h/7d usage near 95-100%).

    Returns `{"main_calls": int, "sub_calls": int, "session_ids": [...],
    "quota_written": bool}`.
    """
    import random

    from ..synth.scenarios import rate_limit_pct, scaled_count, subagent_probability

    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    config_dir = config_dir.rstrip(os.sep)
    project_dir = os.path.join(config_dir, "projects", "-home-demo-project")
    os.makedirs(project_dir, exist_ok=True)

    main_models = ["claude-sonnet-5"]
    sub_models = ["claude-haiku-4-5", "claude-sonnet-5"]
    sub_prob = subagent_probability(scenario)
    tool_choices = [None, "Bash", "Read", "Edit", "Grep", "WebSearch",
                    "mcp__github__list", "TodoWrite"]

    main_calls = 0
    sub_calls = 0
    session_ids: list[str] = []
    quota_snapshots: list[tuple[datetime, float, float]] = []

    for day_offset in range(days - 1, -1, -1):
        day = now - timedelta(days=day_offset)
        n_calls = (events_per_day if scenario == "steady"
                  else scaled_count(scenario, day, day_offset, events_per_day))
        if n_calls <= 0:
            continue
        session_id = f"sess-{day.strftime('%Y%m%d')}"
        session_ids.append(session_id)
        main_lines: list[str] = []
        sub_lines: dict[str, list[str]] = {}

        for i in range(n_calls):
            ts = (day.replace(hour=9, minute=0, second=0, microsecond=0)
                 + timedelta(minutes=i * 7, seconds=rng.randint(0, 59)))
            msg_id, req_id = f"m-{session_id}-{i}", f"r-{session_id}-{i}"
            tool = rng.choice(tool_choices)
            inp, out = rng.randint(200, 6000), rng.randint(100, 3000)
            cr, cw = rng.randint(0, 30000), rng.randint(0, 5000)

            if rng.random() < sub_prob:
                agent_name = f"sub-{rng.randint(1, 3)}"
                model = rng.choice(sub_models)
                lines = sub_lines.setdefault(agent_name, [])
                for suffix in ("", "-b"):
                    lines.append(_synthetic_transcript_line(
                        ts, msg_id, req_id, model=model, tool=tool, session=session_id,
                        inp=inp, out=out, cr=cr, cw=cw, agent=agent_name, block_suffix=suffix))
                sub_calls += 1
            else:
                model = rng.choice(main_models)
                for suffix in ("", "-b"):
                    main_lines.append(_synthetic_transcript_line(
                        ts, msg_id, req_id, model=model, tool=tool, session=session_id,
                        inp=inp, out=out, cr=cr, cw=cw, block_suffix=suffix))
                main_calls += 1

        with open(os.path.join(project_dir, f"{session_id}.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(main_lines) + ("\n" if main_lines else ""))

        if sub_lines:
            subagents_dir = os.path.join(project_dir, session_id, "subagents")
            os.makedirs(subagents_dir, exist_ok=True)
            for agent_name, lines in sub_lines.items():
                with open(os.path.join(subagents_dir, f"agent-{agent_name}.jsonl"), "w",
                         encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")

        base_primary = min(95.0, 4.0 + day_offset * 2.0)
        base_secondary = min(90.0, 3.0 + day_offset * 1.5)
        primary, secondary = rate_limit_pct(scenario, day_offset, days, base_primary, base_secondary)
        quota_snapshots.append((day.replace(hour=23, minute=59, second=0, microsecond=0),
                               primary, secondary))

    # Status-line quota.json / quota_history.jsonl live one directory up from
    # CLAUDE_CONFIG_DIR (mirrors `token-finops collect-statusline`'s
    # `~/.token-finops/...`, independent of `~/.claude`).
    home_dir = os.path.dirname(config_dir) or config_dir
    quota_dir = os.path.join(home_dir, ".token-finops")
    quota_written = False
    if quota_snapshots:
        os.makedirs(quota_dir, exist_ok=True)
        history_lines = []
        for observed_at, primary, secondary in quota_snapshots:
            snap = {
                "observed_at": observed_at.isoformat(),
                "rate_limits": {
                    "five_hour": {"used_percentage": primary,
                                 "resets_at": (observed_at + timedelta(hours=5)).isoformat()},
                    "seven_day": {"used_percentage": secondary,
                                 "resets_at": (observed_at + timedelta(days=7)).isoformat()},
                },
                "model": "claude-sonnet-5",
            }
            history_lines.append(json.dumps(snap))
        with open(os.path.join(quota_dir, "quota_history.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(history_lines) + "\n")
        with open(os.path.join(quota_dir, "quota.json"), "w", encoding="utf-8") as fh:
            fh.write(history_lines[-1])
        quota_written = True

    return {"main_calls": main_calls, "sub_calls": sub_calls, "session_ids": session_ids,
            "quota_written": quota_written}
