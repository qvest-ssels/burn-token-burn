from __future__ import annotations

from token_finops.adapters.hermes import HermesAdapter, build_synthetic_hermes
from token_finops.core.model import Status, Unit
from token_finops.core.runway import compute_runway


def test_hermes_synthetic(tmp_path, monkeypatch):
    root = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(root))

    n = build_synthetic_hermes(str(root), sessions=12, seed=1)
    assert n == 12

    adapter = HermesAdapter()
    assert adapter.available()

    events = adapter.events()
    assert len(events) == 12

    local_events = [e for e in events if e.is_local_model]
    openrouter_events = [e for e in events if e.model_raw.startswith("anthropic/")]
    assert local_events, "expected at least one local (Ollama) row"
    for e in local_events:
        assert e.usd_estimate is None
        assert e.tags.get("billing_provider") == "ollama"
        assert e.tags.get("billing_mode") == "unknown"

    assert openrouter_events, "expected at least one openrouter row"
    for e in openrouter_events:
        assert e.native_unit == Unit.USD
        assert e.native_cost is not None and e.native_cost > 0
        assert e.usd_estimate is not None and e.usd_estimate > 0

    child_events = [e for e in events if e.agent_id]
    assert child_events, "expected the sub-agent session to carry agent_id"
    for e in child_events:
        assert e.initiator == "agent"

    policy = adapter.default_policy()
    assert policy.unit == Unit.USD
    assert policy.allowance is None

    runway = compute_runway(events, policy)
    assert runway.status == Status.UNLIMITED


def test_hermes_not_available(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "nope"))
    adapter = HermesAdapter()
    assert not adapter.available()
    assert list(adapter.scan()) == []
