"""Shared fixtures: an isolated HOME, a fixed clock, synthetic Copilot DBs and
Claude Code transcript trees. Nothing here touches the real ~/. or the network."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from token_finops_cli.core.model import BudgetPolicy, CycleKind, Unit, UsageEvent

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

# Environment variables that point adapters at their data. All are redirected
# into the temporary HOME so a developer's real telemetry never leaks in.
_TOOL_ENV = (
    "TOKEN_FINOPS_COPILOT_DB", "TOKEN_FINOPS_DB", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "GEMINI_CLI_HOME",
    "HERMES_HOME", "CONTINUE_GLOBAL_DIR", "CLINE_CLI_HOME", "TOKEN_FINOPS_CLINE_DIRS",
    "TOKEN_FINOPS_OPENCODE_DB", "TOKEN_FINOPS_AIDER_DIRS", "TOKEN_FINOPS_AIDER_ANALYTICS",
    "TOKEN_FINOPS_ENERGY_JSON", "TOKEN_FINOPS_HARDWARE_JSON", "XDG_DATA_HOME", "APPDATA",
)

# User settings (core/config.py). Unlike the adapter roots above these are read on
# *every* BudgetPolicy construction, so they must be neutralised for the whole suite,
# not just for tests that take the `home` fixture -- otherwise a developer who has a
# real ~/.token-finops/config.json would get different thresholds than CI.
_CONFIG_ENV = (
    "TOKEN_FINOPS_CONFIG", "TOKEN_FINOPS_WARN_AT", "TOKEN_FINOPS_CRITICAL_AT",
    "TOKEN_FINOPS_DEFAULT_TOOL", "TOKEN_FINOPS_CYCLE_DAY", "TOKEN_FINOPS_BUDGET",
    "TOKEN_FINOPS_ALLOWANCE", "TOKEN_FINOPS_WINDOW_HOURS",
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point every test at a config file that does not exist, drop the settings env
    vars, and clear the process-level CLI overrides / warn-once memory."""
    from token_finops_cli.core import config

    for var in _CONFIG_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TOKEN_FINOPS_CONFIG", str(tmp_path / "no-such-config.json"))
    config.reset()
    yield
    config.reset()


@pytest.fixture
def write_config(tmp_path, monkeypatch):
    """Write a `~/.token-finops/config.json` for this test and point the CLI at it."""
    def _write(data: dict) -> str:
        path = tmp_path / "token-finops-config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setenv("TOKEN_FINOPS_CONFIG", str(path))
        return str(path)

    return _write


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway HOME. Every adapter root resolves below it (and does not
    exist unless a test creates it); the Claude Code quota files are
    redirected as well because the adapter expands them at import time."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    for var in _TOOL_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(h / ".claude"))
    monkeypatch.setenv("XDG_DATA_HOME", str(h / ".local" / "share"))
    # Aider treats "~" itself as a search root, so it is always "available";
    # point it at a directory that does not exist.
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_DIRS", str(h / "no-aider"))
    monkeypatch.setenv("TOKEN_FINOPS_CLINE_DIRS", str(h / "no-cline"))

    from token_finops_cli.adapters import claude_code
    from token_finops_cli.core import pricing
    monkeypatch.setattr(claude_code, "QUOTA_FILE", str(h / ".token-finops" / "quota.json"))
    monkeypatch.setattr(claude_code, "QUOTA_HISTORY_FILE", str(h / ".token-finops" / "quota_history.jsonl"))
    monkeypatch.setattr(pricing, "_TABLE", None)
    yield h
    monkeypatch.setattr(pricing, "_TABLE", None)


@pytest.fixture
def run_cli(capsys):
    """Run `token-finops <argv>` in-process and return stdout."""
    from token_finops_cli.cli import main

    def _run(*argv: str) -> str:
        main(list(argv))
        return capsys.readouterr().out

    return _run


# --------------------------------------------------------------------------- #
# Event / policy builders
# --------------------------------------------------------------------------- #
def make_event(days_ago: float = 0.0, *, now: datetime = NOW, tool: str = "copilot", model: str = "gpt-5",
               aiu: float | None = 100.0, usd: float | None = None, session: str = "s1", agent: str = "",
               inp: int = 1000, out: int = 200, cr: int = 0, cw: int = 0, reasoning: int = 0,
               duration_ms: float | None = None, native_unit: Unit | None = Unit.AIU, **tags) -> UsageEvent:
    return UsageEvent(ts_utc=now - timedelta(days=days_ago), tool=tool, model_raw=model,
                      input_tokens=inp, output_tokens=out, cache_read_tokens=cr, cache_write_tokens=cw,
                      reasoning_tokens=reasoning, session_id=session, agent_id=agent,
                      native_cost=aiu, native_unit=native_unit if aiu is not None else None,
                      usd_estimate=usd, duration_ms=duration_ms, tags=dict(tags))


def month_policy(allowance: float | None = 3000.0, cycle_day: int = 1, **kw) -> BudgetPolicy:
    return BudgetPolicy(tool="copilot", window_id="month", unit=Unit.AIU,
                        cycle=CycleKind.CALENDAR_MONTH_UTC, allowance=allowance, cycle_day=cycle_day, **kw)


def percent_policy(hours: int = 5, allowance: float | None = 1.0, tool: str = "claude_code") -> BudgetPolicy:
    return BudgetPolicy(tool=tool, window_id=f"{hours}h", unit=Unit.PERCENT, cycle=CycleKind.ROLLING,
                        window_length=timedelta(hours=hours), allowance=allowance,
                        source_of_truth="provider_pct")


# --------------------------------------------------------------------------- #
# Synthetic Copilot DB with explicit rows
# --------------------------------------------------------------------------- #
def write_copilot_db(path, rows: list[dict]) -> None:
    """rows: dicts with ts (datetime), session, inp, out, nano_aiu, and optional
    model/agent/reasoning/duration_ms. Uses the full (extra-column) schema."""
    con = sqlite3.connect(str(path))
    con.execute(
        """CREATE TABLE assistant_usage_events (
            session_id TEXT, created_at TEXT, input_tokens INTEGER, output_tokens INTEGER,
            reasoning_tokens INTEGER, duration_ms REAL, total_nano_aiu INTEGER,
            model TEXT, cache_read_tokens INTEGER, cache_write_tokens INTEGER, agent_id TEXT,
            parent_tool_call_id TEXT, initiator TEXT, request_multiplier REAL)"""
    )
    con.executemany(
        "INSERT INTO assistant_usage_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r.get("session", "s1"), r["ts"].isoformat(), r.get("inp", 1000), r.get("out", 200),
          r.get("reasoning", 0), r.get("duration_ms", 1000.0), r.get("nano_aiu", 100 * 10**9),
          r.get("model", "gpt-5"), r.get("cr", 0), r.get("cw", 0), r.get("agent", ""),
          r.get("parent", ""), r.get("initiator", "user"), 1.0) for r in rows],
    )
    con.commit()
    con.close()


# --------------------------------------------------------------------------- #
# Claude Code transcript builder
# --------------------------------------------------------------------------- #
def transcript_line(ts: datetime, msg_id: str, req_id: str, *, model: str = "claude-sonnet-5",
                    tool: str | None = None, agent: str = "", session: str = "sess-1",
                    inp: int = 5, out: int = 50, cr: int = 20_000, cw: int = 1_000, cw_1h: int = 0,
                    block_suffix: str = "") -> str:
    content = ([{"type": "tool_use", "id": "toolu_1", "name": tool, "input": {}}] if tool
               else [{"type": "text", "text": "hi"}])
    e = {
        "type": "assistant", "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "sessionId": session, "requestId": req_id, "uuid": f"u-{msg_id}{block_suffix}",
        "isSidechain": bool(agent), "cwd": "/w",
        "message": {"id": msg_id, "model": model, "role": "assistant", "content": content,
                    "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr,
                              "cache_creation_input_tokens": cw,
                              "cache_creation": {"ephemeral_1h_input_tokens": cw_1h,
                                                 "ephemeral_5m_input_tokens": cw - cw_1h}}},
    }
    if agent:
        e["agentId"] = agent
    return json.dumps(e)


def write_transcript(path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_claude_tree(config_dir, now: datetime = NOW, session: str = "sess-1") -> dict:
    """A CLAUDE_CONFIG_DIR with one project, one main transcript (with duplicated
    content-block lines) and two sub-agent transcripts on different models.
    Returns the expected deduplicated structure for assertions."""
    proj = config_dir / "projects" / "-home-x"
    main = proj / f"{session}.jsonl"
    write_transcript(main, [
        # m1 is one API response spread over two content-block lines (dup)
        transcript_line(now, "m1", "r1", tool=None, session=session),
        transcript_line(now, "m1", "r1", tool="Bash", session=session, block_suffix="-b"),
        transcript_line(now + timedelta(minutes=1), "m2", "r2", tool="WebSearch", session=session),
        transcript_line(now + timedelta(minutes=2), "m3", "r3", tool="mcp__github__list", session=session),
        transcript_line(now + timedelta(minutes=3), "m4", "r4", tool=None, session=session, out=500),
        transcript_line(now + timedelta(minutes=4), "m5", "r5", tool="Agent", session=session),
        transcript_line(now + timedelta(minutes=5), "m6", "r6", tool="TodoWrite", session=session),
        transcript_line(now + timedelta(minutes=6), "m7", "r7", tool="mcp__claude-in-chrome__navigate",
                        session=session),
        # a second block far later -> second 5h billing block
        transcript_line(now + timedelta(hours=7), "m8", "r8", tool="Read", session=session),
        transcript_line(now + timedelta(hours=7), "m8", "r8", tool="Grep", session=session, block_suffix="-b"),
        '{"type":"user","message":{"role":"user","content":"x"}}',
        "not json at all",
        '{"type":"assistant","message":{"id":"nousage","model":"claude-sonnet-5","content":[]}}',
    ])
    subs = proj / session / "subagents"
    write_transcript(subs / "agent-haiku1.jsonl", [
        transcript_line(now + timedelta(minutes=2, seconds=10), "h1", "hr1", model="claude-haiku-4-5",
                        agent="haiku1", session=session, out=200),
        transcript_line(now + timedelta(minutes=2, seconds=20), "h2", "hr2", model="claude-haiku-4-5",
                        agent="haiku1", session=session, out=200),
    ])
    write_transcript(subs / "agent-sonnet1.jsonl", [
        transcript_line(now + timedelta(minutes=4, seconds=10), "s1", "sr1", model="claude-sonnet-5",
                        agent="sonnet1", session=session, out=1000),
    ])
    return {"main_calls": 8, "sub_calls": 3, "total": 11, "session": session,
            "buckets": {"File & shell ops": 2, "Web research": 1, "Connectors (MCP)": 1,
                        "Text / reasoning": 1, "Sub-agent launches": 1, "Other tools": 1,
                        "Claude in Chrome": 1}}
