"""GitHub Copilot CLI adapter — port of oh-my-agent-code/token-finops-cli.

Source: ~/.copilot/session-store.db, table `assistant_usage_events`.
Budget unit: AI units / credits (`total_nano_aiu / 1e9`; 1 credit = $0.01).
Cycle: calendar month, reset 00:00 UTC on the 1st (GitHub's cycle; override
with --cycle-day if your enterprise contract differs).

Differences from the original:
- opens the DB with immutable=1 (never locks the live DB),
- reads the extra columns when present (model, cache tokens, agent_id,
  parent_tool_call_id, initiator, request_multiplier) so sub-agent calls are
  attributable,
- emits UsageEvents for the shared runway engine instead of computing its
  own report.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from ..core.model import BudgetPolicy, CycleKind, Unit, UsageEvent
from .base import BaseAdapter, register, sqlite_readonly

DEFAULT_BUDGET_AIU = 50_000.0  # the original's default; Pro=1500, Pro+=7000, Max=20000

OPTIONAL_COLUMNS = (
    "model", "cache_read_tokens", "cache_write_tokens", "agent_id",
    "parent_tool_call_id", "initiator", "request_multiplier",
)


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    cur = con.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _parse_ts(s: str) -> datetime:
    s = (s or "").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # epoch millis fallback
        dt = datetime.fromtimestamp(float(s) / 1000.0, tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@register
class CopilotAdapter(BaseAdapter):
    tool = "copilot"
    display_name = "GitHub Copilot CLI"

    def default_root(self) -> str:
        return os.environ.get("TOKEN_FINOPS_COPILOT_DB", "~/.copilot/session-store.db")

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        if not os.path.exists(self.root):
            return
        con = sqlite_readonly(self.root)
        try:
            cols = _columns(con, "assistant_usage_events")
            if not cols:
                return
            extra = [c for c in OPTIONAL_COLUMNS if c in cols]
            select = ["session_id", "created_at", "input_tokens", "output_tokens",
                      "reasoning_tokens", "duration_ms", "total_nano_aiu", *extra]
            where = ""
            params: list = []
            if since is not None:
                where = "WHERE created_at >= ?"
                params.append(since.astimezone(timezone.utc).isoformat())
            cur = con.execute(
                f"SELECT {', '.join(select)} FROM assistant_usage_events {where} ORDER BY created_at",
                params,
            )
            idx = {name: i for i, name in enumerate(select)}
            for row in cur:
                def g(name, default=None):
                    i = idx.get(name)
                    return row[i] if i is not None and row[i] is not None else default

                yield UsageEvent(
                    ts_utc=_parse_ts(g("created_at", "")),
                    tool=self.tool,
                    model_raw=str(g("model", "copilot")),
                    input_tokens=int(g("input_tokens", 0)),
                    output_tokens=int(g("output_tokens", 0)),
                    cache_read_tokens=int(g("cache_read_tokens", 0)),
                    cache_write_tokens=int(g("cache_write_tokens", 0)),
                    reasoning_tokens=int(g("reasoning_tokens", 0)),
                    reasoning_is_subset_of_output=True,
                    session_id=str(g("session_id", "")),
                    agent_id=str(g("agent_id", "")),
                    parent_id=str(g("parent_tool_call_id", "")),
                    initiator=str(g("initiator", "")),
                    native_cost=float(g("total_nano_aiu", 0)) / 1e9,
                    native_unit=Unit.AIU,
                    duration_ms=float(g("duration_ms", 0.0)),
                    event_id=f"{g('session_id','')}:{g('created_at','')}",
                )
        finally:
            con.close()

    def default_policy(self, allowance: Optional[float] = None, cycle_day: int = 1) -> BudgetPolicy:
        return BudgetPolicy(
            tool=self.tool, window_id="month", unit=Unit.AIU,
            cycle=CycleKind.CALENDAR_MONTH_UTC, cycle_day=cycle_day,
            allowance=DEFAULT_BUDGET_AIU if allowance is None else allowance,
            source_of_truth="local_sum",
        )


def build_synthetic_db(path: str, days: int = 14, events_per_day: int = 8, seed: int = 42,
                       with_extra_columns: bool = True, scenario: str = "steady",
                       now: Optional[datetime] = None) -> int:
    """Synthetic session-store.db for demos/tests (from the original repo,
    extended with the optional columns the real CLI writes).

    `scenario` (see `synth.scenarios`) shapes per-day volume and, for
    "exhausted", scales the AI-unit cost per event so total usage over the
    period lands past the default 50,000 AIU monthly allowance. The default
    "steady" scenario reproduces the exact pre-scenario output for the same
    seed/days/events_per_day."""
    import random
    from datetime import timedelta

    from ..synth.scenarios import adjust_for_weekend, copilot_volume_multiplier, scaled_count

    rng = random.Random(seed)
    if os.path.exists(path):
        os.remove(path)  # re-generating: start from a clean db, not an append
    con = sqlite3.connect(path)
    cur = con.cursor()
    extra_ddl = (
        ", model TEXT, cache_read_tokens INTEGER, cache_write_tokens INTEGER, agent_id TEXT,"
        " parent_tool_call_id TEXT, initiator TEXT, request_multiplier REAL"
        if with_extra_columns else ""
    )
    cur.execute(
        f"""CREATE TABLE assistant_usage_events (
            session_id TEXT, created_at TEXT, input_tokens INTEGER, output_tokens INTEGER,
            reasoning_tokens INTEGER, duration_ms REAL, total_nano_aiu INTEGER{extra_ddl})"""
    )
    now = now or datetime.now(timezone.utc)
    rows = []
    models = ["gpt-5", "claude-sonnet-4-5", "gpt-5-mini"]
    vol_mult = copilot_volume_multiplier(scenario)
    for day_offset in range(days):
        day = now - timedelta(days=day_offset)
        session_id = f"demo-session-{day_offset // 3}"
        n_events = (events_per_day if scenario == "steady"
                   else scaled_count(scenario, day, day_offset, events_per_day))
        for _ in range(n_events):
            ts = day - timedelta(minutes=rng.randint(0, 1439))
            ts = adjust_for_weekend(scenario, ts)
            inp, out, reas = rng.randint(200, 4000), rng.randint(100, 2500), rng.randint(0, 800)
            dur = rng.uniform(800, 15000)
            nano = int((inp + out) * rng.uniform(150_000_000, 400_000_000) * vol_mult)
            base = (session_id, ts.isoformat(), inp, out, reas, dur, nano)
            if with_extra_columns:
                sub = rng.random() < 0.25
                base += (rng.choice(models), rng.randint(0, 20000), rng.randint(0, 3000),
                         "explore-agent" if sub else "", "call-1" if sub else "",
                         "agent" if sub else "user", 1.0)
            rows.append(base)
    if rows:
        ph = ", ".join("?" * len(rows[0]))
        cur.executemany(f"INSERT INTO assistant_usage_events VALUES ({ph})", rows)
    con.commit()
    con.close()
    return len(rows)
