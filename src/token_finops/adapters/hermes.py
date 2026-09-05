"""Hermes Agent (Nous Research) adapter.

Source: ${HERMES_HOME:-~/.hermes}/state.db (SQLite, WAL).

Newer Hermes builds write a `session_model_usage` table (session x model x
billing_provider granularity); older builds only have `sessions` (one event
per session row). We check `sqlite_master` and prefer the newer table,
falling back to `sessions`, and use `PRAGMA table_info` throughout so we
tolerate whichever columns a given build happens to have.

Dedup key: `event_id = f"{session_id}:{model}:{billing_provider}"` for the
session_model_usage path (one row per session/model/provider triple is
already unique in that table) or just `session_id` for the sessions
fallback.

Also optionally parses legacy per-session JSONL logs at
`${root}/sessions/*.jsonl` if present (older Hermes builds before the
sqlite state store existed).
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from urllib.parse import urlparse

from ..core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Unit, UsageEvent
from ..core.pricing import estimate_usd, is_local_model
from .base import BaseAdapter, register, sqlite_readonly

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"}
LOCAL_PROVIDERS = {"ollama", "lmstudio", "lm-studio", "vllm", "local", "custom"}


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
        num = float(s)
        return _parse_ts(num)
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


def _is_local(billing_mode, billing_base_url, billing_provider, model) -> bool:
    if (billing_mode or "").strip().lower() == "unknown":
        return True
    if billing_base_url:
        try:
            host = urlparse(billing_base_url).hostname
        except ValueError:
            host = None
        if host and host.lower() in LOCAL_HOSTS:
            return True
    prov = (billing_provider or "").strip().lower()
    if prov in LOCAL_PROVIDERS:
        return True
    if is_local_model(model or ""):
        return True
    return False


def _build_event(
    *,
    session_id: str,
    model: str,
    billing_provider: str,
    billing_base_url: str,
    billing_mode: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    reasoning_tokens: int,
    estimated_cost_usd,
    actual_cost_usd,
    ts_utc: datetime,
    source: str,
    title: str,
    parent_session_id: str,
    event_id: str,
) -> UsageEvent:
    local = _is_local(billing_mode, billing_base_url, billing_provider, model)
    native_cost = None
    native_unit = None
    usd_estimate = None
    tags: dict = {}

    if local:
        tags["billing_provider"] = billing_provider or ""
        tags["billing_mode"] = billing_mode or ""
    else:
        cost = actual_cost_usd if actual_cost_usd else estimated_cost_usd
        if not cost:
            cost = estimate_usd(model, input_tokens, output_tokens,
                                 cache_read_tokens, cache_write_tokens)
        usd_estimate = cost
        if (billing_provider or "").strip().lower() == "openrouter" and cost is not None:
            native_cost = cost
            native_unit = Unit.USD

    agent_id = parent_session_id or ""
    initiator = "agent" if agent_id else "user"

    return UsageEvent(
        ts_utc=ts_utc,
        tool="hermes",
        model_raw=model or "",
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        cache_read_tokens=int(cache_read_tokens or 0),
        cache_write_tokens=int(cache_write_tokens or 0),
        reasoning_tokens=int(reasoning_tokens or 0),
        reasoning_is_subset_of_output=True,
        session_id=session_id,
        agent_id=agent_id,
        parent_id=parent_session_id or "",
        initiator=initiator,
        native_cost=native_cost,
        native_unit=native_unit,
        usd_estimate=usd_estimate,
        is_local_model=local,
        cwd="",
        event_id=event_id,
        tags=tags,
    )


@register
class HermesAdapter(BaseAdapter):
    tool = "hermes"
    display_name = "Hermes Agent"

    def default_root(self) -> str:
        return os.environ.get("HERMES_HOME", "~/.hermes")

    @property
    def db_path(self) -> str:
        return os.path.join(self.root, "state.db")

    def available(self) -> bool:
        return os.path.exists(self.db_path)

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        seen: set[str] = set()
        if os.path.exists(self.db_path):
            yield from self._scan_db(since, seen)
        yield from self._scan_legacy_jsonl(since, seen)

    def _scan_db(self, since: Optional[datetime], seen: set[str]) -> Iterable[UsageEvent]:
        con = sqlite_readonly(self.db_path)
        try:
            if _table_exists(con, "session_model_usage"):
                yield from self._scan_session_model_usage(con, since, seen)
            elif _table_exists(con, "sessions"):
                yield from self._scan_sessions_only(con, since, seen)
        finally:
            con.close()

    def _scan_session_model_usage(self, con: sqlite3.Connection,
                                   since: Optional[datetime],
                                   seen: set[str]) -> Iterable[UsageEvent]:
        smu_cols = _columns(con, "session_model_usage")
        if not smu_cols or "session_id" not in smu_cols:
            return
        sess_cols = _columns(con, "sessions") if _table_exists(con, "sessions") else set()

        smu_select = [c for c in (
            "session_id", "model", "billing_provider", "billing_base_url",
            "billing_mode", "input_tokens", "output_tokens", "cache_read_tokens",
            "cache_write_tokens", "reasoning_tokens", "estimated_cost_usd",
            "actual_cost_usd", "cost_status",
        ) if c in smu_cols]
        sess_select = [c for c in (
            "started_at", "ended_at", "source", "title", "parent_session_id",
            "billing_base_url", "billing_mode",
        ) if c in sess_cols]

        cur = con.execute(f"SELECT {', '.join(smu_select)} FROM session_model_usage")
        smu_idx = {name: i for i, name in enumerate(smu_select)}
        rows = cur.fetchall()

        sess_by_id: dict[str, dict] = {}
        if sess_select:
            scur = con.execute(f"SELECT session_id, {', '.join(sess_select)} FROM sessions"
                                if "session_id" in sess_cols else
                                f"SELECT id, {', '.join(sess_select)} FROM sessions")
            s_idx = {name: i + 1 for i, name in enumerate(sess_select)}
            for srow in scur:
                sess_by_id[str(srow[0])] = {name: srow[i] for name, i in s_idx.items()}

        for row in rows:
            def g(name, default=None):
                i = smu_idx.get(name)
                return row[i] if i is not None and row[i] is not None else default

            session_id = str(g("session_id", ""))
            sess = sess_by_id.get(session_id, {})
            started_at = sess.get("started_at")
            ended_at = sess.get("ended_at")
            ts_utc = _parse_ts(ended_at) or _parse_ts(started_at)
            if ts_utc is None:
                continue
            if since is not None and ts_utc < since:
                continue

            model = g("model", "")
            billing_provider = g("billing_provider", "")
            event_id = f"{session_id}:{model}:{billing_provider}"
            if event_id in seen:
                continue
            seen.add(event_id)

            yield _build_event(
                session_id=session_id,
                model=model,
                billing_provider=billing_provider,
                billing_base_url=sess.get("billing_base_url", ""),
                billing_mode=sess.get("billing_mode", ""),
                input_tokens=g("input_tokens", 0),
                output_tokens=g("output_tokens", 0),
                cache_read_tokens=g("cache_read_tokens", 0),
                cache_write_tokens=g("cache_write_tokens", 0),
                reasoning_tokens=g("reasoning_tokens", 0),
                estimated_cost_usd=g("estimated_cost_usd"),
                actual_cost_usd=g("actual_cost_usd"),
                ts_utc=ts_utc,
                source=sess.get("source", ""),
                title=sess.get("title", ""),
                parent_session_id=sess.get("parent_session_id", ""),
                event_id=event_id,
            )

    def _scan_sessions_only(self, con: sqlite3.Connection,
                             since: Optional[datetime],
                             seen: set[str]) -> Iterable[UsageEvent]:
        cols = _columns(con, "sessions")
        if not cols:
            return
        id_col = "id" if "id" in cols else ("session_id" if "session_id" in cols else None)
        if id_col is None:
            return
        select = [id_col] + [c for c in (
            "source", "model", "started_at", "ended_at", "billing_provider",
            "billing_base_url", "billing_mode", "input_tokens", "output_tokens",
            "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
            "estimated_cost_usd", "actual_cost_usd", "cost_status",
            "parent_session_id", "title",
        ) if c in cols]
        cur = con.execute(f"SELECT {', '.join(select)} FROM sessions")
        idx = {name: i for i, name in enumerate(select)}

        for row in cur:
            def g(name, default=None):
                i = idx.get(name)
                return row[i] if i is not None and row[i] is not None else default

            session_id = str(g(id_col, ""))
            ts_utc = _parse_ts(g("ended_at")) or _parse_ts(g("started_at"))
            if ts_utc is None:
                continue
            if since is not None and ts_utc < since:
                continue
            if session_id in seen:
                continue
            seen.add(session_id)

            yield _build_event(
                session_id=session_id,
                model=g("model", ""),
                billing_provider=g("billing_provider", ""),
                billing_base_url=g("billing_base_url", ""),
                billing_mode=g("billing_mode", ""),
                input_tokens=g("input_tokens", 0),
                output_tokens=g("output_tokens", 0),
                cache_read_tokens=g("cache_read_tokens", 0),
                cache_write_tokens=g("cache_write_tokens", 0),
                reasoning_tokens=g("reasoning_tokens", 0),
                estimated_cost_usd=g("estimated_cost_usd"),
                actual_cost_usd=g("actual_cost_usd"),
                ts_utc=ts_utc,
                source=g("source", ""),
                title=g("title", ""),
                parent_session_id=g("parent_session_id", ""),
                event_id=session_id,
            )

    def _scan_legacy_jsonl(self, since: Optional[datetime],
                            seen: set[str]) -> Iterable[UsageEvent]:
        pattern = os.path.join(self.root, "sessions", "*.jsonl")
        for path in sorted(glob.glob(pattern)):
            session_id = os.path.splitext(os.path.basename(path))[0]
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        usage = rec.get("usage")
                        model = rec.get("model")
                        if not isinstance(usage, dict) or not model:
                            continue
                        ts_utc = (_parse_ts(rec.get("ts")) or _parse_ts(rec.get("timestamp"))
                                  or _parse_ts(rec.get("ended_at")) or _parse_ts(rec.get("started_at")))
                        if ts_utc is None:
                            continue
                        if since is not None and ts_utc < since:
                            continue
                        inp = usage.get("input_tokens", usage.get("prompt_tokens", 0))
                        out = usage.get("output_tokens", usage.get("completion_tokens", 0))
                        cache_read = usage.get("cache_read_tokens", 0)
                        cache_write = usage.get("cache_write_tokens", 0)
                        reasoning = usage.get("reasoning_tokens", 0)
                        event_id = f"legacy:{session_id}:{ts_utc.isoformat()}"
                        if event_id in seen:
                            continue
                        seen.add(event_id)
                        yield _build_event(
                            session_id=session_id,
                            model=model,
                            billing_provider=rec.get("billing_provider", ""),
                            billing_base_url=rec.get("billing_base_url", ""),
                            billing_mode=rec.get("billing_mode", ""),
                            input_tokens=inp,
                            output_tokens=out,
                            cache_read_tokens=cache_read,
                            cache_write_tokens=cache_write,
                            reasoning_tokens=reasoning,
                            estimated_cost_usd=rec.get("estimated_cost_usd"),
                            actual_cost_usd=rec.get("actual_cost_usd"),
                            ts_utc=ts_utc,
                            source=rec.get("source", "legacy_jsonl"),
                            title=rec.get("title", ""),
                            parent_session_id=rec.get("parent_session_id", ""),
                            event_id=event_id,
                        )
            except OSError:
                continue

    def quota(self) -> Optional[QuotaSnapshot]:
        # TODO: OpenRouter exposes GET https://openrouter.ai/api/v1/key
        # (Authorization: Bearer <key>) returning
        # {"data": {"limit": ..., "limit_remaining": ..., "usage": ...}} plus
        # a usage_daily breakdown on some accounts. This is the official
        # OpenRouter key-info endpoint. Not called here — this tool never
        # makes network requests on its own; wire this up behind an
        # explicit --online flag if/when that's added, using the API key
        # from Hermes's own config (not read here).
        return None

    def default_policy(self, allowance: Optional[float] = None) -> BudgetPolicy:
        return BudgetPolicy(
            tool=self.tool, window_id="30d", unit=Unit.USD,
            cycle=CycleKind.SLIDING_FROM_FIRST_USE,
            window_length=timedelta(days=30),
            allowance=allowance,
            source_of_truth="local_sum",
        )


def build_synthetic_hermes(root_dir: str, sessions: int = 12, seed: int = 1) -> int:
    """Create a synthetic `${root_dir}/state.db` with both `sessions` and
    `session_model_usage` tables, mixing OpenRouter (billed), Nous portal
    (billed, unknown pricing -> pricing table fallback), and local Ollama
    (unbilled) rows. One session is a sub-agent (parent_session_id set).
    Returns the number of session_model_usage rows written."""
    import random

    rng = random.Random(seed)
    os.makedirs(root_dir, exist_ok=True)
    db_path = os.path.join(root_dir, "state.db")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        """CREATE TABLE sessions (
            id TEXT PRIMARY KEY, source TEXT, model TEXT, started_at TEXT, ended_at TEXT,
            message_count INTEGER, api_call_count INTEGER, input_tokens INTEGER,
            output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
            reasoning_tokens INTEGER, billing_provider TEXT, billing_base_url TEXT,
            billing_mode TEXT, estimated_cost_usd REAL, actual_cost_usd REAL,
            cost_status TEXT, cost_source TEXT, parent_session_id TEXT, title TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE session_model_usage (
            session_id TEXT, model TEXT, billing_provider TEXT, input_tokens INTEGER,
            output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
            reasoning_tokens INTEGER, estimated_cost_usd REAL, actual_cost_usd REAL,
            cost_status TEXT
        )"""
    )

    now = datetime.now(timezone.utc)
    sess_rows = []
    smu_rows = []
    for i in range(sessions):
        sid = f"hermes-session-{i}"
        started = now - timedelta(hours=rng.randint(1, 24 * 20), minutes=rng.randint(0, 59))
        ended = started + timedelta(minutes=rng.randint(1, 45))
        inp, out = rng.randint(500, 8000), rng.randint(200, 4000)
        cache_read, cache_write = rng.randint(0, 3000), rng.randint(0, 500)
        reasoning = rng.randint(0, 500)

        kind = rng.choice(["openrouter", "openrouter", "nous_portal", "local"])
        parent_id = ""
        if kind == "local":
            model = "qwen3:32b"
            billing_provider = "ollama"
            billing_base_url = "http://localhost:11434"
            billing_mode = "unknown"
            estimated_cost_usd = None
            actual_cost_usd = None
            cost_status = "not_billed"
        elif kind == "openrouter":
            model = "anthropic/claude-sonnet-4-5"
            billing_provider = "openrouter"
            billing_base_url = "https://openrouter.ai/api/v1"
            billing_mode = "metered"
            actual_cost_usd = round((inp * 3.0 + out * 15.0) / 1e6, 6)
            estimated_cost_usd = actual_cost_usd
            cost_status = "billed"
        else:  # nous_portal
            model = "hermes-4-405b"
            billing_provider = "nous_portal"
            billing_base_url = "https://portal.nousresearch.com/api/v1"
            billing_mode = "metered"
            estimated_cost_usd = round((inp * 1.0 + out * 3.0) / 1e6, 6)
            actual_cost_usd = None
            cost_status = "estimated"

        # make the last session a sub-agent of the first one, regardless of kind
        if sessions > 1 and i == sessions - 1:
            parent_id = "hermes-session-0"

        sess_rows.append((
            sid, "cli", model, started.isoformat(), ended.isoformat(),
            rng.randint(1, 20), rng.randint(1, 20), inp, out, cache_read, cache_write,
            reasoning, billing_provider, billing_base_url, billing_mode,
            estimated_cost_usd, actual_cost_usd, cost_status, "hermes",
            parent_id, f"demo session {i}",
        ))
        smu_rows.append((
            sid, model, billing_provider, inp, out, cache_read, cache_write,
            reasoning, estimated_cost_usd, actual_cost_usd, cost_status,
        ))

    cur.executemany(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        sess_rows,
    )
    cur.executemany(
        "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        smu_rows,
    )
    con.commit()
    con.close()
    return len(smu_rows)
