"""OpenCode / Kilo CLI adapter.

Source: SQLite databases at
`${XDG_DATA_HOME:-~/.local/share}/opencode/opencode.db` (OpenCode) and
`~/.local/share/kilo/kilo.db` (Kilo CLI, a fork/relative sharing the same
schema shape). Override with `TOKEN_FINOPS_OPENCODE_DB` (colon-separated
list of explicit db paths) to point at either or both directly.

The relevant table is `session_message`: one row per chat turn, with a
`data` TEXT column holding a JSON blob per assistant turn shaped roughly as
`{model: {id, providerID}, modelID, providerID, cost, tokens: {input,
output, reasoning, cache: {read, write}}, time: {created}}`. A `session` (or
newer `session_v2`) table carries `id`, `title`, `directory`/`cwd` and
`parent_id`/`parentID` (set when the session is a sub-agent spawned by
another session).

Dedup key: `event_id = f"{source}:{session_id}:{message_id}"` where
`source` is `"opencode"` or `"kilo"` depending on which db the row came
from — the two tools never share ids so this also protects against reading
both dbs when both happen to exist.

Also optionally parses the legacy per-message JSON store at
`${dirname(db)}/storage/message/<session_id>/<message_id>.json` (same
shape as the `data` column) for older builds that predate the sqlite
message table, or that still keep both around.

No local budget/quota concept is exposed by either tool (see
docs/adr/0006-opencode-kilo-cli.md) — `quota()` is always `None` and
`default_policy()` follows the BYO-key convention used for Hermes: `Unit.USD`,
`CycleKind.SLIDING_FROM_FIRST_USE` over 30 days, `allowance=None` (unlimited
until the user sets one).
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Unit, UsageEvent
from ..core.pricing import estimate_usd, is_local_model
from .base import BaseAdapter, register, sqlite_readonly

LOCAL_PROVIDERS = {"ollama", "lmstudio", "lm-studio", "local", "llama.cpp", "vllm"}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    cur = con.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    cur = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def _parse_ts(value) -> Optional[datetime]:
    """Accept epoch seconds, epoch millis, or an ISO-8601 string."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:  # epoch millis
            v /= 1000.0
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return _parse_ts(float(s))
    except ValueError:
        pass
    s2 = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _default_db_paths() -> list[str]:
    data_home = os.path.expanduser(os.environ.get("XDG_DATA_HOME", "~/.local/share"))
    return [
        os.path.join(data_home, "opencode", "opencode.db"),
        os.path.expanduser("~/.local/share/kilo/kilo.db"),
    ]


def _source_for(db_path: str) -> str:
    return "kilo" if "kilo" in os.path.basename(os.path.dirname(db_path)).lower() \
        or "kilo" in os.path.basename(db_path).lower() else "opencode"


def _event_from_payload(data: dict, *, session_id: str, source: str,
                         fallback_ts, sessions: dict, event_id: str) -> Optional[UsageEvent]:
    if not isinstance(data, dict):
        return None

    model_field = data.get("model")
    if isinstance(model_field, dict):
        model_id = model_field.get("id") or model_field.get("modelID") or ""
        provider_id = model_field.get("providerID") or model_field.get("provider") or ""
    else:
        model_id = data.get("modelID") or ""
        provider_id = data.get("providerID") or ""
    if not model_id:
        return None

    tokens = data.get("tokens") or {}
    if not isinstance(tokens, dict):
        tokens = {}
    input_tokens = int(tokens.get("input") or 0)
    output_tokens = int(tokens.get("output") or 0)
    reasoning_tokens = int(tokens.get("reasoning") or 0)
    cache = tokens.get("cache") or {}
    if not isinstance(cache, dict):
        cache = {}
    cache_read = int(cache.get("read") or 0)
    cache_write = int(cache.get("write") or 0)

    ts = None
    time_field = data.get("time")
    if isinstance(time_field, dict):
        ts = _parse_ts(time_field.get("created"))
    if ts is None:
        ts = _parse_ts(fallback_ts)
    if ts is None:
        return None

    provider_norm = (provider_id or "").strip().lower()
    local = provider_norm in LOCAL_PROVIDERS or is_local_model(model_id)

    cost = data.get("cost")
    usd_estimate: Optional[float] = None
    if not local:
        if isinstance(cost, (int, float)) and cost > 0:
            usd_estimate = float(cost)
        else:
            # OpenCode reports reasoning tokens separately from output; for
            # pricing purposes (no provider gives us a distinct reasoning
            # rate here) fold them into output tokens.
            usd_estimate = estimate_usd(
                model_id, input_tokens, output_tokens + reasoning_tokens,
                cache_read, cache_write,
            )

    sess = sessions.get(session_id, {})
    parent_id = sess.get("parent_id") or ""
    cwd = sess.get("cwd") or ""

    return UsageEvent(
        ts_utc=ts,
        tool="opencode",
        model_raw=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        reasoning_tokens=reasoning_tokens,
        reasoning_is_subset_of_output=False,
        session_id=session_id,
        agent_id=parent_id,
        parent_id=parent_id,
        initiator="agent" if parent_id else "user",
        native_cost=None,
        native_unit=None,
        usd_estimate=usd_estimate,
        is_local_model=local,
        cwd=cwd,
        event_id=event_id,
        tags={"provider": provider_id or "", "source": source},
    )


@register
class OpencodeAdapter(BaseAdapter):
    tool = "opencode"
    display_name = "OpenCode / Kilo CLI"

    def __init__(self, root: Optional[str] = None):
        env = os.environ.get("TOKEN_FINOPS_OPENCODE_DB")
        if root:
            self.db_paths = [os.path.expanduser(root)]
        elif env:
            self.db_paths = [os.path.expanduser(p) for p in env.split(":") if p.strip()]
        else:
            self.db_paths = _default_db_paths()
        self.root = self.db_paths[0] if self.db_paths else ""

    def default_root(self) -> str:
        return _default_db_paths()[0]

    def available(self) -> bool:
        return any(os.path.exists(p) for p in self.db_paths)

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        seen: set[str] = set()
        for db_path in self.db_paths:
            source = _source_for(db_path)
            if os.path.exists(db_path):
                yield from self._scan_db(db_path, source, since, seen)
            yield from self._scan_legacy_json(db_path, source, since, seen)

    def _load_sessions(self, con: sqlite3.Connection) -> dict[str, dict]:
        sessions: dict[str, dict] = {}
        session_table = None
        for t in ("session_v2", "session"):
            if _table_exists(con, t):
                session_table = t
                break
        if session_table is None:
            return sessions
        cols = _columns(con, session_table)
        id_col = "id" if "id" in cols else None
        if id_col is None:
            return sessions
        parent_col = next((c for c in ("parent_id", "parentID") if c in cols), None)
        dir_col = next((c for c in ("directory", "cwd") if c in cols), None)
        title_col = "title" if "title" in cols else None
        select = [id_col] + [c for c in (parent_col, dir_col, title_col) if c]
        cur = con.execute(f"SELECT {', '.join(select)} FROM {session_table}")
        idx = {name: i for i, name in enumerate(select)}
        for row in cur:
            sid = str(row[idx[id_col]])
            sessions[sid] = {
                "parent_id": (row[idx[parent_col]] if parent_col else None) or "",
                "cwd": (row[idx[dir_col]] if dir_col else None) or "",
                "title": (row[idx[title_col]] if title_col else None) or "",
            }
        return sessions

    def _scan_db(self, db_path: str, source: str, since: Optional[datetime],
                 seen: set[str]) -> Iterable[UsageEvent]:
        con = sqlite_readonly(db_path)
        try:
            if not _table_exists(con, "session_message"):
                return
            sessions = self._load_sessions(con)
            cols = _columns(con, "session_message")
            data_col = "data" if "data" in cols else None
            if data_col is None:
                return
            id_col = "id" if "id" in cols else None
            session_col = next((c for c in ("session_id", "sessionID") if c in cols), None)
            role_col = next((c for c in ("role", "type") if c in cols), None)
            time_col = "time_created" if "time_created" in cols else None
            select = [c for c in (id_col, session_col, role_col, data_col, time_col) if c]
            cur = con.execute(f"SELECT {', '.join(select)} FROM session_message")
            idx = {name: i for i, name in enumerate(select)}

            for row in cur:
                def g(name):
                    i = idx.get(name)
                    return row[i] if i is not None else None

                role = g(role_col) if role_col else None
                if role is not None and str(role).strip().lower() != "assistant":
                    continue

                raw_data = g(data_col)
                if not raw_data:
                    continue
                try:
                    data = json.loads(raw_data)
                except (ValueError, TypeError):
                    continue

                message_id = str(g(id_col) or "")
                session_id = str(g(session_col) or "")
                event_id = f"{source}:{session_id}:{message_id}"
                if event_id in seen:
                    continue

                ev = _event_from_payload(
                    data, session_id=session_id, source=source,
                    fallback_ts=g(time_col), sessions=sessions, event_id=event_id,
                )
                if ev is None:
                    continue
                seen.add(event_id)
                yield ev
        finally:
            con.close()

    def _scan_legacy_json(self, db_path: str, source: str, since: Optional[datetime],
                           seen: set[str]) -> Iterable[UsageEvent]:
        root_dir = os.path.dirname(db_path)
        pattern = os.path.join(root_dir, "storage", "message", "*", "*.json")
        for path in sorted(glob.glob(pattern)):
            session_id = os.path.basename(os.path.dirname(path))
            message_id = os.path.splitext(os.path.basename(path))[0]
            event_id = f"{source}:legacy:{session_id}:{message_id}"
            if event_id in seen:
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            ev = _event_from_payload(
                data, session_id=session_id, source=source,
                fallback_ts=None, sessions={}, event_id=event_id,
            )
            if ev is None:
                continue
            seen.add(event_id)
            yield ev

    def events(self, since: Optional[datetime] = None) -> list[UsageEvent]:
        evs = list(self.scan(since))
        if since is not None:
            evs = [e for e in evs if e.ts_utc >= since]
        evs.sort(key=lambda e: e.ts_utc)
        return evs

    def quota(self) -> Optional[QuotaSnapshot]:
        return None

    def default_policy(self, allowance: Optional[float] = None) -> BudgetPolicy:
        return BudgetPolicy(
            tool=self.tool, window_id="30d", unit=Unit.USD,
            cycle=CycleKind.SLIDING_FROM_FIRST_USE,
            window_length=timedelta(days=30),
            allowance=allowance,
            source_of_truth="local_sum",
        )


def build_synthetic_opencode(db_path: str, sessions: int = 6, seed: int = 1,
                             scenario: str = "steady", now: Optional[datetime] = None) -> int:
    """Create a synthetic OpenCode/Kilo-shaped `opencode.db` at `db_path` with
    `session` and `session_message` tables, mixing anthropic/claude-sonnet-4-5
    (with `cost` set), openai/gpt-5 (no `cost` -> pricing table fallback) and
    ollama/qwen3:32b (local, unbilled) assistant turns. One session is a
    sub-agent of the first (`parent_id` set).

    `scenario` (see `synth.scenarios`) scales the total session count and
    shapes how far back timestamps land; "steady" (the default) reproduces
    the exact pre-scenario output for the same seed/sessions.

    Returns the number of assistant `session_message` rows written."""
    import random

    from ..synth.scenarios import adjust_for_weekend, session_count_multiplier, session_hour_offset

    if scenario != "steady":
        sessions = max(1, round(sessions * session_count_multiplier(scenario)))
    rng = random.Random(seed)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)  # re-generating: start from a clean db, not an append
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        """CREATE TABLE session (
            id TEXT PRIMARY KEY, title TEXT, directory TEXT, parent_id TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE session_message (
            id TEXT PRIMARY KEY, session_id TEXT, role TEXT, data TEXT, time_created INTEGER
        )"""
    )

    now = now or datetime.now(timezone.utc)
    sess_rows = []
    msg_rows = []
    n_assistant = 0
    max_hours = 24 * 20
    for i in range(sessions):
        sid = f"opencode-session-{i}"
        parent_id = ""
        if sessions > 1 and i == sessions - 1:
            parent_id = "opencode-session-0"
        sess_rows.append((sid, f"demo session {i}", f"/repo/project-{i}", parent_id))

        # Guarantee a mix of all three kinds regardless of seed/session count,
        # then let the RNG pick for any remaining sessions.
        kinds_cycle = ["anthropic", "openai", "ollama"]
        if i < len(kinds_cycle):
            kind = kinds_cycle[i]
        else:
            kind = rng.choice(["anthropic", "anthropic", "openai", "ollama"])
        if scenario == "steady":
            created_dt = now - timedelta(hours=rng.randint(1, max_hours), minutes=rng.randint(0, 59))
        else:
            hours_ago = session_hour_offset(scenario, rng, max_hours)
            created_dt = adjust_for_weekend(scenario, now - timedelta(hours=hours_ago,
                                                                        minutes=rng.randint(0, 59)))
        created_ms = int(created_dt.timestamp() * 1000)
        inp, out = rng.randint(500, 8000), rng.randint(200, 4000)
        cache_read, cache_write = rng.randint(0, 3000), rng.randint(0, 500)
        reasoning = rng.randint(0, 500)

        if kind == "anthropic":
            model_id, provider_id = "claude-sonnet-4-5", "anthropic"
            cost = round((inp * 3.0 + out * 15.0) / 1e6, 6)
        elif kind == "openai":
            model_id, provider_id = "gpt-5", "openai"
            cost = None
        else:
            model_id, provider_id = "qwen3:32b", "ollama"
            cost = None

        data = {
            "model": {"id": model_id, "providerID": provider_id},
            "cost": cost,
            "tokens": {
                "input": inp, "output": out, "reasoning": reasoning,
                "cache": {"read": cache_read, "write": cache_write},
            },
            "time": {"created": created_ms},
        }
        # user turn precedes the assistant turn (no data.tokens/cost expected)
        msg_rows.append((f"{sid}-msg-user", sid, "user",
                          json.dumps({"time": {"created": created_ms - 1000}}), created_ms - 1))
        msg_rows.append((f"{sid}-msg-assistant", sid, "assistant",
                          json.dumps(data), created_ms))
        n_assistant += 1

    cur.executemany("INSERT INTO session VALUES (?,?,?,?)", sess_rows)
    cur.executemany("INSERT INTO session_message VALUES (?,?,?,?,?)", msg_rows)
    con.commit()
    con.close()
    return n_assistant
