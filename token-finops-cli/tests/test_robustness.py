"""Schema drift and corruption resilience, per adapter.

AGENTS.md rule 7: "Parsers use field-alias lists, skip unparsable lines, never
raise on one bad record". This module takes each adapter's own
`build_synthetic_*()` output and then *breaks* it the way a real machine does:
garbage appended to a JSONL that was being written when the laptop slept, a
SQLite store from an older build with half the columns missing, unknown model
ids, timestamps in four different encodings, empty files, a directory where a
file should be, and finally 200 rounds of randomly-shaped JSON.

Every test asserts the same contract: `available()` / `scan()` must not raise,
and whatever survived the damage must still be parsed.

Everything runs against tmp_path under the shared `home` fixture (no real ~/,
no network).
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from token_finops_cli.adapters.aider import (AiderAdapter, build_synthetic_aider,
                                             parse_analytics_jsonl, parse_history_file)
from token_finops_cli.adapters.claude_code import (ClaudeCodeAdapter, build_synthetic_claude_code,
                                                   parse_transcript)
from token_finops_cli.adapters.cline import ClineAdapter, build_synthetic_cline
from token_finops_cli.adapters.cline import _parse_ts_ms as cline_ts
from token_finops_cli.adapters.codex import CodexAdapter, build_synthetic_codex, parse_rollout
from token_finops_cli.adapters.continue_dev import (ContinueAdapter, build_synthetic_continue,
                                                    parse_session_file)
from token_finops_cli.adapters.continue_dev import _parse_ts as continue_ts
from token_finops_cli.adapters.copilot import CopilotAdapter, build_synthetic_db
from token_finops_cli.adapters.gemini_cli import GeminiCliAdapter, build_synthetic_gemini, parse_jsonl
from token_finops_cli.adapters.gemini_cli import _parse_ts as gemini_ts
from token_finops_cli.adapters.hermes import HermesAdapter, build_synthetic_hermes
from token_finops_cli.adapters.hermes import _parse_ts as hermes_ts
from token_finops_cli.adapters.opencode import OpencodeAdapter, build_synthetic_opencode
from token_finops_cli.adapters.opencode import _parse_ts as opencode_ts

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

# What a half-written / hand-edited / log-rotated JSONL grows at the end.
GARBAGE_LINES = (
    "not json at all\n",
    '{"type": "assistant", "message": {"usage": \n',      # truncated mid-object
    "\n",
    "     \n",
    "[1, 2, 3]\n",                                        # valid JSON, wrong shape
    "null\n",
    '{"unterminated": "string\n',
    "�� binary-ish junk\n",
)


def append_garbage(path: str) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.writelines(GARBAGE_LINES)


def jsonl_files(root: str) -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        out += [os.path.join(dirpath, n) for n in filenames if n.endswith(".jsonl")]
    return sorted(out)


# --------------------------------------------------------------------------- #
# Builders: one synthetic tree per adapter, returned with its adapter.
# --------------------------------------------------------------------------- #
def build_claude(home, monkeypatch):
    cfg = os.path.join(str(home), ".claude")
    build_synthetic_claude_code(cfg, days=3, seed=1, now=NOW)
    return ClaudeCodeAdapter(os.path.join(cfg, "projects")), os.path.join(cfg, "projects")


def build_codex(home, monkeypatch):
    root = os.path.join(str(home), ".codex")
    build_synthetic_codex(root, days=3, sessions_per_day=2, seed=1, now=NOW)
    return CodexAdapter(root), root


def build_gemini(home, monkeypatch):
    root = os.path.join(str(home), ".gemini")
    build_synthetic_gemini(root, days=3, seed=1, now=NOW)
    return GeminiCliAdapter(root), root


def build_aider(home, monkeypatch):
    root = os.path.join(str(home), "work")
    build_synthetic_aider(root, scenario="burst", now=NOW)
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_DIRS", root)
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_ANALYTICS", os.path.join(root, ".aider", "analytics.jsonl"))
    return AiderAdapter(), root


def build_continue(home, monkeypatch):
    root = os.path.join(str(home), ".continue")
    build_synthetic_continue(root, now=NOW)
    return ContinueAdapter(root), root


JSONL_TOOLS = {
    "claude_code": build_claude,
    "codex": build_codex,
    "gemini_cli": build_gemini,
    "aider": build_aider,
}


# --------------------------------------------------------------------------- #
# (a) garbage / truncation in JSONL sources
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tool", sorted(JSONL_TOOLS))
def test_appended_garbage_keeps_every_intact_event(home, monkeypatch, tool):
    adapter, root = JSONL_TOOLS[tool](home, monkeypatch)
    before = adapter.events()
    assert before, f"{tool} fixture produced no events"

    files = jsonl_files(root)
    assert files, f"{tool} wrote no .jsonl to corrupt"
    for path in files:
        append_garbage(path)

    after = adapter.events()
    assert len(after) == len(before)
    assert {e.event_id for e in after} == {e.event_id for e in before}


@pytest.mark.parametrize("tool", sorted(JSONL_TOOLS))
def test_truncated_tail_never_raises(home, monkeypatch, tool):
    adapter, root = JSONL_TOOLS[tool](home, monkeypatch)
    before = len(adapter.events())
    for path in jsonl_files(root):
        size = os.path.getsize(path)
        with open(path, "r+", encoding="utf-8") as fh:
            fh.truncate(int(size * 0.6))  # cut mid-line, as a killed write would
    after = adapter.events()  # must not raise
    assert 0 <= len(after) <= before


def test_continue_corrupt_session_file_does_not_hide_the_others(home, monkeypatch):
    adapter, root = build_continue(home, monkeypatch)
    before = adapter.events()
    assert len(before) >= 2
    sessions_dir = os.path.join(root, "sessions")
    victim = sorted(n for n in os.listdir(sessions_dir) if n != "sessions.json")[0]
    with open(os.path.join(sessions_dir, victim), "w", encoding="utf-8") as fh:
        fh.write('{"history": [{"promptTokens": 1,')  # truncated JSON
    after = adapter.events()
    assert 1 <= len(after) < len(before)


def test_continue_broken_index_still_parses_sessions(home, monkeypatch):
    adapter, root = build_continue(home, monkeypatch)
    with open(os.path.join(root, "sessions", "sessions.json"), "w", encoding="utf-8") as fh:
        fh.write("not json")
    assert len(adapter.events()) >= 2  # index is only metadata; usage survives


def test_binary_bytes_in_a_transcript_are_replaced_not_fatal(home, monkeypatch):
    adapter, root = build_claude(home, monkeypatch)
    before = len(adapter.events())
    target = jsonl_files(root)[0]
    with open(target, "ab") as fh:
        fh.write(b'{"type":"assistant","message":{"usage":{"input_tokens":1}}, "x":"\xff\xfe"}\n')
    assert len(adapter.events()) >= before  # decodes with replacement, no UnicodeDecodeError


# --------------------------------------------------------------------------- #
# (b) missing columns / older SQLite schemas
# --------------------------------------------------------------------------- #
def test_copilot_minimal_schema_without_model_or_cache_columns(home):
    path = os.path.join(str(home), "minimal.db")
    n = build_synthetic_db(path, days=4, seed=3, with_extra_columns=False, now=NOW)
    events = CopilotAdapter(path).events()
    assert len(events) == n
    for ev in events:
        assert ev.model_raw == "copilot"      # falls back, does not KeyError
        assert ev.cache_read_tokens == 0
        assert ev.cache_write_tokens == 0
        assert ev.native_cost is not None


def test_hermes_sessions_table_only(home):
    root = os.path.join(str(home), ".hermes")
    build_synthetic_hermes(root, sessions=8, seed=3, now=NOW)
    adapter = HermesAdapter(root)
    before = len(adapter.events())
    con = sqlite3.connect(os.path.join(root, "state.db"))
    con.execute("DROP TABLE session_model_usage")
    con.commit()
    con.close()
    after = adapter.events()
    assert after, "sessions-only fallback produced nothing"
    assert len(after) <= before
    assert all(ev.ts_utc.tzinfo is not None for ev in after)


def test_hermes_sessions_table_without_optional_columns(home):
    root = os.path.join(str(home), ".hermes-min")
    os.makedirs(root, exist_ok=True)
    con = sqlite3.connect(os.path.join(root, "state.db"))
    con.execute("CREATE TABLE sessions (id TEXT, started_at TEXT, input_tokens INTEGER,"
                " output_tokens INTEGER)")
    con.execute("INSERT INTO sessions VALUES (?,?,?,?)", ("s1", NOW.isoformat(), 100, 20))
    con.commit()
    con.close()
    events = HermesAdapter(root).events()
    assert len(events) == 1
    assert events[0].session_id == "s1"


def test_opencode_without_cost_column_falls_back_to_pricing(home):
    db = os.path.join(str(home), "opencode.db")
    build_synthetic_opencode(db, sessions=6, seed=3, now=NOW)
    con = sqlite3.connect(db)
    rows = con.execute("SELECT id, data FROM session_message WHERE role = 'assistant'").fetchall()
    for msg_id, raw in rows:
        data = json.loads(raw)
        data.pop("cost", None)
        con.execute("UPDATE session_message SET data = ? WHERE id = ?", (json.dumps(data), msg_id))
    con.commit()
    con.close()

    events = OpencodeAdapter(db).events()
    assert len(events) == len(rows)
    billed = [e for e in events if not e.is_local_model]
    assert billed and all(e.usd_estimate is None or e.usd_estimate > 0 for e in billed)


def test_opencode_without_session_table(home):
    db = os.path.join(str(home), "opencode-nosess.db")
    build_synthetic_opencode(db, sessions=4, seed=3, now=NOW)
    con = sqlite3.connect(db)
    con.execute("DROP TABLE session")
    con.commit()
    con.close()
    events = OpencodeAdapter(db).events()
    assert events
    assert all(ev.cwd == "" and ev.parent_id == "" for ev in events)


def test_copilot_rows_with_text_in_numeric_columns_and_bad_timestamps(home):
    path = os.path.join(str(home), "drifted.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE assistant_usage_events (session_id TEXT, created_at TEXT,"
                " input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER,"
                " duration_ms REAL, total_nano_aiu INTEGER)")
    con.executemany("INSERT INTO assistant_usage_events VALUES (?,?,?,?,?,?,?)", [
        ("s1", NOW.isoformat(), 100, 20, 0, 1000.0, 10 ** 9),          # good
        ("s2", "n/a", 100, 20, 0, 1000.0, 10 ** 9),                     # unparsable ts -> dropped
        ("s3", NOW.isoformat(), "lots", "some", None, "slow", "many"),  # TEXT in INTEGER columns
    ])
    con.commit()
    con.close()
    events = CopilotAdapter(path).events()
    assert len(events) == 2
    assert {e.session_id for e in events} == {"s1", "s3"}
    assert all(e.input_tokens >= 0 and e.native_cost is not None for e in events)


def test_codex_rollout_with_drifted_payload_shapes(home):
    root = os.path.join(str(home), ".codex")
    day_dir = os.path.join(root, "sessions", "2026", "09", "15")
    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, "rollout-drift.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for rec in (
            {"type": "event_msg", "payload": ["not", "a", "dict"]},
            {"type": "event_msg", "payload": {"type": "token_count", "info": "a string"}},
            {"type": "session_meta", "payload": {"id": "s1"}},
            {"type": "event_msg", "payload": {"type": "token_count", "timestamp": NOW.isoformat(),
                                              "info": {"total_token_usage": {"input_tokens": 10,
                                                                             "output_tokens": 5},
                                                       "rate_limits": {"primary": ["drifted"],
                                                                       "secondary": {
                                                                           "used_percent": "82",
                                                                           "resets_at": 1e19}}}}},
        ):
            fh.write(json.dumps(rec) + "\n")
    adapter = CodexAdapter(root)
    events = adapter.events()
    assert len(events) == 1
    primary, secondary = adapter.quotas()      # must not raise on either window
    assert primary is None
    assert secondary is not None and secondary.used_fraction == pytest.approx(0.82)
    assert secondary.resets_at is None         # out-of-range epoch, not a crash


def test_claude_quota_file_with_drifted_shape(home, monkeypatch):
    from token_finops_cli.adapters import claude_code as cc

    quota = os.path.join(str(home), "quota.json")
    monkeypatch.setattr(cc, "QUOTA_FILE", quota)
    monkeypatch.setattr(cc, "QUOTA_HISTORY_FILE", os.path.join(str(home), "quota_history.jsonl"))
    adapter = cc.ClaudeCodeAdapter(os.path.join(str(home), "projects"))
    for payload in ('[1, 2, 3]', '{"rate_limits": "gone"}',
                    '{"rate_limits": {"five_hour": {"used_percentage": "n/a"}}}',
                    '{"rate_limits": {"five_hour": {"used_percentage": 40, "resets_at": 1e19}}}'):
        with open(quota, "w", encoding="utf-8") as fh:
            fh.write(payload)
        snap = adapter.quota()   # must never raise
        assert snap is None or snap.used_fraction == pytest.approx(0.4)


# --------------------------------------------------------------------------- #
# (c) unknown extra fields / unknown model ids
# --------------------------------------------------------------------------- #
UNKNOWN_MODEL = "acme-mystery-model-9000"


def _assert_priced_or_none(events):
    assert events
    for ev in events:
        assert ev.usd_estimate is None or ev.usd_estimate > 0
        assert ev.model_norm  # normalisation never raises, never returns None


def test_claude_transcript_with_unknown_model_and_extra_fields(home):
    path = os.path.join(str(home), "sess-x.jsonl")
    line = {
        "type": "assistant", "timestamp": NOW.isoformat().replace("+00:00", "Z"),
        "sessionId": "sess-x", "requestId": "r1", "uuid": "u1",
        "brandNewField": {"nested": [1, {"deep": True}]}, "anotherOne": 12.5,
        "message": {"id": "m1", "model": UNKNOWN_MODEL, "role": "assistant",
                    "content": [{"type": "tool_use", "name": "Bash", "surprise": 1}],
                    "usage": {"input_tokens": 10, "output_tokens": 20,
                              "cache_read_input_tokens": 5, "future_counter": 99}},
    }
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    events = list(parse_transcript(path))
    assert len(events) == 1
    assert events[0].model_raw == UNKNOWN_MODEL
    _assert_priced_or_none(events)


def test_gemini_message_with_unknown_model_and_extra_fields(home):
    path = os.path.join(str(home), "session-x.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"sessionId": "s1", "unknownMeta": {"a": 1}}) + "\n")
        fh.write(json.dumps({"type": "gemini", "id": "g1", "timestamp": NOW.isoformat(),
                             "model": UNKNOWN_MODEL, "somethingNew": [1, 2],
                             "tokens": {"input": 100, "output": 50, "cached": 10,
                                        "thoughts": 5, "futureField": "?"}}) + "\n")
    events = list(parse_jsonl(path, str(home), {}))
    assert len(events) == 1
    _assert_priced_or_none(events)


def test_continue_item_with_unknown_model_and_alias_drift(home):
    sessions_dir = os.path.join(str(home), ".continue", "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    path = os.path.join(sessions_dir, "sess-y.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"history": [
            {"message": {"role": "assistant"}, "model": UNKNOWN_MODEL, "brandNew": {"x": 1},
             "usage": {"prompt_tokens": 300, "completion_tokens": 40, "reasoning_tokens": 7},
             "timestamp": int(NOW.timestamp() * 1000)},
            {"message": {"role": "assistant"}, "nothing": "useful"},
        ]}, fh)
    events = list(parse_session_file(path, {}))
    assert len(events) == 1
    assert events[0].input_tokens == 300
    _assert_priced_or_none(events)


def test_cline_task_with_unknown_model_and_extra_payload_keys(home, monkeypatch):
    root = os.path.join(str(home), "globalStorage")
    task_dir = os.path.join(root, "saoudrizwan.claude-dev", "tasks", "task-x")
    os.makedirs(task_dir, exist_ok=True)
    payload = {"tokensIn": 500, "tokensOut": 100, "cacheReads": 3, "cacheWrites": 1,
               "apiProtocol": "anthropic", "brandNewKey": {"deep": [1, 2]}}
    entries = [{"ts": int(NOW.timestamp() * 1000), "type": "say", "say": "api_req_started",
                "text": json.dumps(payload), "extra": "ignored"}]
    with open(os.path.join(task_dir, "ui_messages.json"), "w", encoding="utf-8") as fh:
        json.dump(entries, fh)
    with open(os.path.join(task_dir, "task_metadata.json"), "w", encoding="utf-8") as fh:
        json.dump({"model_usage": [{"model_id": UNKNOWN_MODEL}], "futureField": 1}, fh)
    monkeypatch.setenv("TOKEN_FINOPS_CLINE_DIRS", root)
    events = ClineAdapter().events()
    assert len(events) == 1
    assert events[0].model_raw == UNKNOWN_MODEL
    _assert_priced_or_none(events)


def test_cline_task_without_any_model_metadata(home, monkeypatch):
    root = os.path.join(str(home), "globalStorage2")
    build_synthetic_cline(root, tasks=3, seed=2, now=NOW)
    for dirpath, _dirnames, filenames in os.walk(root):
        if "task_metadata.json" in filenames:
            os.remove(os.path.join(dirpath, "task_metadata.json"))
    monkeypatch.setenv("TOKEN_FINOPS_CLINE_DIRS", root)
    events = ClineAdapter().events()
    assert events
    assert all(ev.model_raw == "unknown" for ev in events)


# --------------------------------------------------------------------------- #
# (d) timestamps in odd formats -> always aware UTC
# --------------------------------------------------------------------------- #
def _assert_utc(dt) -> None:
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(0)


EPOCH_S = int(NOW.timestamp())
EPOCH_MS = int(NOW.timestamp() * 1000)
FUTURE_ISO = "2099-01-01T00:00:00Z"


@pytest.mark.parametrize("parser", [hermes_ts, opencode_ts])
@pytest.mark.parametrize("raw", [EPOCH_S, EPOCH_MS, str(EPOCH_S), str(EPOCH_MS),
                                 "2026-09-15T12:00:00", "2026-09-15T12:00:00Z",
                                 "2026-09-15T12:00:00+02:00", FUTURE_ISO])
def test_sqlite_timestamp_formats_normalise_to_utc(parser, raw):
    _assert_utc(parser(raw))


@pytest.mark.parametrize("raw", [EPOCH_MS, float(EPOCH_MS), str(EPOCH_MS)])
def test_cline_epoch_millis(raw):
    _assert_utc(cline_ts(raw))


@pytest.mark.parametrize("raw", [EPOCH_S, EPOCH_MS, "2026-09-15T12:00:00", FUTURE_ISO])
def test_continue_timestamp_formats(raw):
    _assert_utc(continue_ts(raw))


@pytest.mark.parametrize("raw", ["2026-09-15T12:00:00", "2026-09-15T12:00:00Z", str(EPOCH_MS),
                                 FUTURE_ISO])
def test_gemini_timestamp_formats(raw):
    _assert_utc(gemini_ts(raw))


@pytest.mark.parametrize("stamp", ["2026-09-15T12:00:00Z", "2026-09-15T12:00:00",
                                   "2026-09-15T14:00:00+02:00", FUTURE_ISO])
def test_claude_transcript_timestamp_formats(home, stamp):
    path = os.path.join(str(home), "ts.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "type": "assistant", "timestamp": stamp, "sessionId": "s", "requestId": "r",
            "message": {"id": "m", "model": "claude-sonnet-5", "content": [],
                        "usage": {"input_tokens": 1, "output_tokens": 1}}}) + "\n")
    events = list(parse_transcript(path))
    assert len(events) == 1
    _assert_utc(events[0].ts_utc)


@pytest.mark.parametrize("stamp", [EPOCH_S, "2026-09-15T12:00:00", FUTURE_ISO])
def test_aider_analytics_timestamp_formats(home, stamp):
    path = os.path.join(str(home), "analytics.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "message_send",
                             "properties": {"prompt_tokens": 10, "completion_tokens": 2,
                                            "main_model": "gpt-4.1", "time": stamp}}) + "\n")
    events = list(parse_analytics_jsonl(path))
    assert len(events) == 1
    _assert_utc(events[0].ts_utc)


def test_aider_history_without_a_chat_header_uses_file_mtime(home):
    path = os.path.join(str(home), ".aider.chat.history.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("> Tokens: 1,000 sent, 200 received. Cost: $0.01 message, $0.01 session.\n")
    events = list(parse_history_file(path))
    assert len(events) == 1
    _assert_utc(events[0].ts_utc)


# --------------------------------------------------------------------------- #
# (e) empty dirs, empty files, a directory where a file belongs, unreadable
# --------------------------------------------------------------------------- #
def _all_adapters_pointed_at(base: str, monkeypatch) -> list:
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", os.path.join(base, ".copilot", "session-store.db"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", os.path.join(base, ".claude"))
    monkeypatch.setenv("CODEX_HOME", os.path.join(base, ".codex"))
    monkeypatch.setenv("GEMINI_CLI_HOME", os.path.join(base, ".gemini"))
    monkeypatch.setenv("HERMES_HOME", os.path.join(base, ".hermes"))
    monkeypatch.setenv("XDG_DATA_HOME", os.path.join(base, ".local", "share"))
    monkeypatch.setenv("TOKEN_FINOPS_OPENCODE_DB",
                       os.path.join(base, ".local", "share", "opencode", "opencode.db"))
    monkeypatch.setenv("TOKEN_FINOPS_CLINE_DIRS", os.path.join(base, "globalStorage"))
    monkeypatch.setenv("CONTINUE_GLOBAL_DIR", os.path.join(base, ".continue"))
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_DIRS", base)
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_ANALYTICS", os.path.join(base, ".aider", "analytics.jsonl"))

    from token_finops_cli.adapters import all_adapters
    return all_adapters()


def test_empty_directories_yield_nothing_and_never_raise(home, monkeypatch):
    base = os.path.join(str(home), "empty")
    for sub in (".copilot", ".claude/projects", ".codex/sessions", ".gemini/tmp", ".hermes",
                ".local/share/opencode", "globalStorage", ".continue/sessions", ".aider"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    for adapter in _all_adapters_pointed_at(base, monkeypatch):
        adapter.available()          # must not raise either way
        assert adapter.events() == []
        assert adapter.quota() is None or adapter.quota() is not None


def test_empty_files_are_tolerated(home, monkeypatch):
    base = os.path.join(str(home), "emptyfiles")
    files = [
        ".copilot/session-store.db",
        ".claude/projects/proj/sess.jsonl",
        ".codex/sessions/2026/09/15/rollout-x.jsonl",
        ".gemini/tmp/hash/chats/session-x.jsonl",
        ".gemini/projects.json",
        ".hermes/state.db",
        ".local/share/opencode/opencode.db",
        "globalStorage/saoudrizwan.claude-dev/tasks/t1/ui_messages.json",
        ".continue/sessions/sessions.json",
        ".continue/sessions/sess-a.json",
        ".aider/analytics.jsonl",
        ".aider.chat.history.md",
    ]
    for rel in files:
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
    for adapter in _all_adapters_pointed_at(base, monkeypatch):
        assert adapter.events() == []


def test_a_directory_where_a_file_belongs_is_skipped(home, monkeypatch):
    base = os.path.join(str(home), "dirs-as-files")
    for rel in (".copilot/session-store.db",
                ".claude/projects/proj/sess.jsonl",
                ".codex/sessions/2026/09/15/rollout-x.jsonl",
                ".gemini/tmp/hash/chats/session-x.jsonl",
                ".hermes/state.db",
                ".local/share/opencode/opencode.db",
                "globalStorage/saoudrizwan.claude-dev/tasks/t1/ui_messages.json",
                ".continue/sessions/sess-a.json",
                ".aider/analytics.jsonl"):
        os.makedirs(os.path.join(base, rel), exist_ok=True)
    for adapter in _all_adapters_pointed_at(base, monkeypatch):
        assert adapter.events() == []


def test_corrupt_sqlite_files_are_skipped(home, monkeypatch):
    base = os.path.join(str(home), "corrupt-db")
    for rel in (".copilot/session-store.db", ".hermes/state.db",
                ".local/share/opencode/opencode.db"):
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"SQLite format 3\x00 but really not" * 50)
    for adapter in _all_adapters_pointed_at(base, monkeypatch):
        assert adapter.events() == []


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root ignores chmod 000")
def test_unreadable_files_are_skipped_not_fatal(home, monkeypatch):
    adapter, root = build_claude(home, monkeypatch)
    before = len(adapter.events())
    victim = jsonl_files(root)[0]
    os.chmod(victim, 0o000)
    try:
        after = adapter.events()      # must not raise PermissionError
    finally:
        os.chmod(victim, 0o644)
    assert 0 <= len(after) <= before


# --------------------------------------------------------------------------- #
# (f) pathological sizes
# --------------------------------------------------------------------------- #
def _claude_line(i: int) -> str:
    return json.dumps({
        "type": "assistant", "timestamp": (NOW - timedelta(minutes=i)).isoformat(),
        "sessionId": "big", "requestId": f"r{i}", "uuid": f"u{i}",
        "message": {"id": f"m{i}", "model": "claude-sonnet-5", "content": [],
                    "usage": {"input_tokens": 10, "output_tokens": 5,
                              "cache_read_input_tokens": 1, "cache_creation_input_tokens": 1}}})


def test_one_megabyte_line_and_ten_thousand_lines_stay_fast(home):
    path = os.path.join(str(home), "big.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("x" * (1024 * 1024) + "\n")                     # 1 MB of junk, no JSON
        fh.write(json.dumps({"type": "assistant", "blob": "y" * (1024 * 1024)}) + "\n")
        for i in range(10_000):
            fh.write(_claude_line(i) + "\n")
    started = time.monotonic()
    events = list(parse_transcript(path))
    elapsed = time.monotonic() - started
    assert len(events) == 10_000
    assert elapsed < 2.0, f"parse_transcript took {elapsed:.2f}s"


def test_ten_thousand_line_rollout_stays_fast(home):
    path = os.path.join(str(home), "rollout-big.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "session_meta", "timestamp": NOW.isoformat(),
                             "payload": {"id": "big", "cwd": "/w"}}) + "\n")
        fh.write("z" * (1024 * 1024) + "\n")
        cum = 0
        for i in range(10_000):
            cum += 10
            fh.write(json.dumps({
                "type": "event_msg", "timestamp": (NOW - timedelta(seconds=i)).isoformat(),
                "payload": {"type": "token_count",
                            "info": {"total_token_usage": {"input_tokens": cum,
                                                           "output_tokens": cum}}}}) + "\n")
    started = time.monotonic()
    events = list(parse_rollout(path))
    elapsed = time.monotonic() - started
    assert len(events) == 10_000
    assert elapsed < 2.0, f"parse_rollout took {elapsed:.2f}s"


# --------------------------------------------------------------------------- #
# (g) fuzz: randomly-shaped records built from the real key vocabulary
# --------------------------------------------------------------------------- #
_KEYS = ("type", "timestamp", "sessionId", "requestId", "uuid", "isSidechain", "agentId",
         "cwd", "parentUuid", "message", "usage", "model", "id", "content", "payload",
         "info", "total_token_usage", "last_token_usage", "rate_limits", "primary",
         "secondary", "used_percent", "resets_at", "input_tokens", "output_tokens",
         "cached_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens",
         "cache_read_input_tokens", "cache_creation_input_tokens", "cache_creation",
         "ephemeral_1h_input_tokens", "tokens", "input", "output", "cached", "thoughts",
         "tool", "total", "promptTokenCount", "candidatesTokenCount", "event",
         "properties", "prompt_tokens", "completion_tokens", "cost", "main_model", "time")

_VALUES = (None, True, False, 0, -1, 3.5, 1e18, float(2**62), "", "assistant", "gemini",
           "token_count", "session_meta", "turn_context", "event_msg", "message_send",
           "2026-09-15T12:00:00Z", "2026-09-15", "not-a-timestamp", "1757500000000",
           [], {}, [1, 2, 3], {"a": 1}, "�", "9" * 40)


def _random_value(rng: random.Random, depth: int = 0):
    if depth < 2 and rng.random() < 0.35:
        if rng.random() < 0.5:
            return {rng.choice(_KEYS): _random_value(rng, depth + 1)
                    for _ in range(rng.randint(0, 4))}
        return [_random_value(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    return rng.choice(_VALUES)


def _random_record(rng: random.Random) -> dict:
    keys = rng.sample(_KEYS, rng.randint(0, 8))
    return {k: _random_value(rng) for k in keys}


@pytest.mark.parametrize("batch", range(10))
def test_fuzz_random_records_never_raise(home, batch):
    """200 seeds total (10 batches x 20), each a small JSONL of randomly shaped
    records fed to all three line-oriented parsers."""
    for seed in range(batch * 20, batch * 20 + 20):
        rng = random.Random(seed)
        path = os.path.join(str(home), f"fuzz-{seed}.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for _ in range(rng.randint(1, 6)):
                fh.write(json.dumps(_random_record(rng)) + "\n")
        for events in (list(parse_transcript(path)),
                       list(parse_rollout(path)),
                       list(parse_jsonl(path, str(home), {})),
                       list(parse_analytics_jsonl(path))):
            for ev in events:
                assert ev.ts_utc.tzinfo is not None
                assert ev.total_tokens >= 0
        os.remove(path)
