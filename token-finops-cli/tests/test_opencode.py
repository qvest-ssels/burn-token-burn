from __future__ import annotations

from token_finops_cli.adapters.opencode import OpencodeAdapter, build_synthetic_opencode
from token_finops_cli.core.model import CycleKind, Status, Unit
from token_finops_cli.core.runway import compute_runway


def test_opencode_synthetic(tmp_path, monkeypatch):
    db_path = tmp_path / "opencode" / "opencode.db"
    monkeypatch.setenv("TOKEN_FINOPS_OPENCODE_DB", str(db_path))

    n = build_synthetic_opencode(str(db_path), sessions=6, seed=1)
    assert n == 6

    adapter = OpencodeAdapter()
    assert adapter.available()

    events = adapter.events()
    assert len(events) == 6

    local_events = [e for e in events if e.is_local_model]
    anthropic_events = [e for e in events if e.tags.get("provider") == "anthropic"]
    openai_events = [e for e in events if e.tags.get("provider") == "openai"]

    assert local_events, "expected at least one local (ollama) row"
    for e in local_events:
        assert e.usd_estimate is None
        assert e.tags.get("source") == "opencode"

    assert anthropic_events, "expected at least one anthropic (billed) row"
    for e in anthropic_events:
        assert e.usd_estimate is not None and e.usd_estimate > 0
        assert not e.is_local_model

    assert openai_events, "expected at least one openai (unbilled cost, pricing fallback) row"
    for e in openai_events:
        assert e.usd_estimate is not None and e.usd_estimate > 0
        assert not e.is_local_model

    child_events = [e for e in events if e.agent_id]
    assert child_events, "expected the sub-agent session to carry agent_id"
    for e in child_events:
        assert e.initiator == "agent"
        assert e.agent_id == "opencode-session-0"

    policy = adapter.default_policy()
    assert policy.unit == Unit.USD
    assert policy.cycle == CycleKind.SLIDING_FROM_FIRST_USE
    assert policy.allowance is None

    runway = compute_runway(events, policy)
    assert runway.status == Status.UNLIMITED


def test_opencode_cost_passthrough(tmp_path, monkeypatch):
    db_path = tmp_path / "opencode" / "opencode.db"
    monkeypatch.setenv("TOKEN_FINOPS_OPENCODE_DB", str(db_path))
    build_synthetic_opencode(str(db_path), sessions=6, seed=1)

    adapter = OpencodeAdapter()
    events = adapter.events()
    anthropic_events = [e for e in events if e.tags.get("provider") == "anthropic"]
    assert anthropic_events
    for e in anthropic_events:
        expected = round((e.input_tokens * 3.0 + e.output_tokens * 15.0) / 1e6, 6)
        assert abs(e.usd_estimate - expected) < 1e-6


def test_opencode_not_available(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_FINOPS_OPENCODE_DB", str(tmp_path / "nope" / "opencode.db"))
    adapter = OpencodeAdapter()
    assert not adapter.available()
    assert list(adapter.scan()) == []
