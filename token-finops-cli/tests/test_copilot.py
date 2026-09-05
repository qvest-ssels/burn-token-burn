import pytest

from token_finops_cli.adapters.copilot import CopilotAdapter, build_synthetic_db
from token_finops_cli.core.model import Status, Unit
from token_finops_cli.core.runway import compute_runway


def test_copilot_scan_and_runway(tmp_path):
    db = tmp_path / "session-store.db"
    n = build_synthetic_db(str(db), days=10, events_per_day=5, seed=1)
    ad = CopilotAdapter(str(db))
    assert ad.available()
    events = ad.events()
    assert len(events) == n
    assert all(e.native_unit == Unit.AIU and e.native_cost > 0 for e in events)
    assert any(e.agent_id for e in events)          # sub-agent attribution from extra columns
    assert any(e.cache_read_tokens for e in events)
    r = compute_runway(events, ad.default_policy(50_000.0))
    assert r.unit == Unit.AIU
    assert r.used > 0
    assert r.status in (Status.OK, Status.WARN, Status.CRITICAL)


def test_copilot_minimal_schema(tmp_path):
    """The original tool's schema (no extra columns) must still parse."""
    db = tmp_path / "old.db"
    build_synthetic_db(str(db), days=3, events_per_day=2, with_extra_columns=False)
    events = CopilotAdapter(str(db)).events()
    assert len(events) == 6
    assert all(e.model_raw == "copilot" and not e.agent_id for e in events)


def test_copilot_missing_db(tmp_path):
    ad = CopilotAdapter(str(tmp_path / "nope.db"))
    assert not ad.available()
    assert ad.events() == []


def test_copilot_timestamp_parsing_variants():
    from datetime import datetime, timezone

    from token_finops_cli.adapters.copilot import _parse_ts

    assert _parse_ts("2026-09-15T12:00:00Z") == datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    assert _parse_ts("2026-09-15T14:00:00+02:00") == datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    assert _parse_ts("2026-09-15T12:00:00") == datetime(2026, 9, 15, 12, tzinfo=timezone.utc)   # naive -> UTC
    assert _parse_ts("1789000000000") == datetime.fromtimestamp(1789000000, tz=timezone.utc)      # epoch ms


def test_copilot_since_filter_and_event_fields(tmp_path):
    from datetime import datetime, timedelta, timezone

    from conftest import write_copilot_db

    now = datetime.now(timezone.utc)
    db = tmp_path / "s.db"
    write_copilot_db(db, [
        {"ts": now - timedelta(days=10), "session": "old", "nano_aiu": 5 * 10**9, "duration_ms": 2500.0},
        {"ts": now - timedelta(minutes=1), "session": "new", "nano_aiu": 7 * 10**9, "agent": "explore",
         "parent": "call-9", "initiator": "agent", "model": "claude-sonnet-4-5", "cr": 300, "cw": 40,
         "reasoning": 12},
    ])
    ad = CopilotAdapter(str(db))
    all_events = ad.events()
    assert [e.session_id for e in all_events] == ["old", "new"]           # sorted by time
    recent = ad.events(since=now - timedelta(days=1))
    assert len(recent) == 1
    e = recent[0]
    assert e.native_cost == pytest.approx(7.0) and e.native_unit == Unit.AIU
    assert (e.agent_id, e.parent_id, e.initiator, e.model_raw) == ("explore", "call-9", "agent", "claude-sonnet-4-5")
    assert (e.cache_read_tokens, e.cache_write_tokens, e.reasoning_tokens) == (300, 40, 12)
    assert e.event_id.startswith("new:") and e.tool == "copilot"
    assert all_events[0].duration_ms == 2500.0


def test_copilot_empty_table_and_missing_table(tmp_path):
    import sqlite3

    db = tmp_path / "empty.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE assistant_usage_events (session_id TEXT, created_at TEXT, input_tokens INTEGER, "
                "output_tokens INTEGER, reasoning_tokens INTEGER, duration_ms REAL, total_nano_aiu INTEGER)")
    con.commit()
    con.close()
    ad = CopilotAdapter(str(db))
    assert ad.available() and ad.events() == []
    other = tmp_path / "other.db"
    con = sqlite3.connect(str(other))
    con.execute("CREATE TABLE unrelated (x INTEGER)")
    con.commit()
    con.close()
    assert CopilotAdapter(str(other)).events() == []


def test_copilot_default_policy_and_root(monkeypatch, tmp_path):
    from token_finops_cli.core.model import CycleKind

    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(tmp_path / "x.db"))
    ad = CopilotAdapter()
    assert ad.root == str(tmp_path / "x.db") and not ad.available()
    p = ad.default_policy()
    assert (p.unit, p.cycle, p.allowance, p.cycle_day, p.source_of_truth) == \
        (Unit.AIU, CycleKind.CALENDAR_MONTH_UTC, 50_000.0, 1, "local_sum")
    p2 = ad.default_policy(1500.0, cycle_day=20)
    assert p2.allowance == 1500.0 and p2.cycle_day == 20
    monkeypatch.delenv("TOKEN_FINOPS_COPILOT_DB")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert CopilotAdapter().root == str(tmp_path / ".copilot" / "session-store.db")


def test_synthetic_db_is_readable_with_immutable_uri(tmp_path):
    from token_finops_cli.adapters.base import sqlite_readonly

    db = tmp_path / "s.db"
    build_synthetic_db(str(db), days=2, events_per_day=2)
    con = sqlite_readonly(str(db))
    try:
        assert con.execute("SELECT COUNT(*) FROM assistant_usage_events").fetchone()[0] == 4
        with pytest.raises(Exception):
            con.execute("DELETE FROM assistant_usage_events")
    finally:
        con.close()
