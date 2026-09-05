from __future__ import annotations

from token_finops_cli.adapters.aider import AiderAdapter, build_synthetic_aider
from token_finops_cli.core.model import CycleKind, Status, Unit
from token_finops_cli.core.runway import compute_runway


def _make_adapter(tmp_path, monkeypatch):
    root = tmp_path / "aider_home"
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_DIRS", str(root))
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_ANALYTICS", str(root / ".aider" / "analytics.jsonl"))
    n_expected = build_synthetic_aider(str(root))
    adapter = AiderAdapter()
    return adapter, n_expected


def test_event_count(tmp_path, monkeypatch):
    adapter, n_expected = _make_adapter(tmp_path, monkeypatch)
    assert adapter.available()
    events = adapter.events()
    assert len(events) == n_expected == 3


def test_number_formats_parsed(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch)
    events = adapter.events()
    history_events = [e for e in events if e.tags.get("ts_approx")]
    assert len(history_events) == 2

    # "3,052 sent, 502 received"
    comma_ev = next(e for e in history_events if e.input_tokens == 3052)
    assert comma_ev.output_tokens == 502

    # "12k sent, 1.5k received"
    k_ev = next(e for e in history_events if e.input_tokens == 12000)
    assert k_ev.output_tokens == 1500


def test_message_cost_passthrough(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch)
    events = adapter.events()
    history_events = [e for e in events if e.tags.get("ts_approx")]
    costs = sorted(e.usd_estimate for e in history_events)
    assert costs == [0.02, 0.15]


def test_analytics_jsonl_cost_passthrough(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch)
    events = adapter.events()
    analytics_events = [e for e in events if not e.tags.get("ts_approx")]
    assert len(analytics_events) == 1
    ev = analytics_events[0]
    assert ev.input_tokens == 800
    assert ev.output_tokens == 200
    assert ev.usd_estimate == 0.01
    assert ev.model_raw == "gpt-4.1"


def test_default_policy_is_unlimited(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch)
    policy = adapter.default_policy()
    assert policy.unit == Unit.USD
    assert policy.cycle == CycleKind.SLIDING_FROM_FIRST_USE
    assert policy.allowance is None

    runway = compute_runway(adapter.events(), policy)
    assert runway.status == Status.UNLIMITED


def test_missing_roots_not_available(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_DIRS", str(tmp_path / "nope"))
    monkeypatch.setenv("TOKEN_FINOPS_AIDER_ANALYTICS", str(tmp_path / "nope" / "analytics.jsonl"))
    adapter = AiderAdapter()
    assert not adapter.available()
    assert list(adapter.scan()) == []
