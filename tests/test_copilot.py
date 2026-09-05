from token_finops.adapters.copilot import CopilotAdapter, build_synthetic_db
from token_finops.core.model import Status, Unit
from token_finops.core.runway import compute_runway


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
