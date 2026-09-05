from __future__ import annotations

from token_finops_cli.adapters.continue_dev import ContinueAdapter, build_synthetic_continue
from token_finops_cli.core.model import CycleKind, Status, Unit
from token_finops_cli.core.runway import compute_runway


def _make_adapter(tmp_path, monkeypatch):
    root = tmp_path / "continue_home"
    monkeypatch.setenv("CONTINUE_GLOBAL_DIR", str(root))
    n_expected = build_synthetic_continue(str(root))
    adapter = ContinueAdapter()
    return adapter, n_expected


def test_event_count(tmp_path, monkeypatch):
    adapter, n_expected = _make_adapter(tmp_path, monkeypatch)
    assert adapter.available()
    events = adapter.events()
    assert len(events) == n_expected == 2


def test_alias_field_parsing(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch)
    events = adapter.events()

    prompt_completion_ev = next(e for e in events if e.model_raw == "gpt-4.1")
    assert prompt_completion_ev.input_tokens == 500
    assert prompt_completion_ev.output_tokens == 120

    usage_ev = next(e for e in events if e.model_raw == "claude-sonnet-4-5")
    assert usage_ev.input_tokens == 1000
    assert usage_ev.output_tokens == 300


def test_low_confidence_tag_and_usd_estimate(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch)
    events = adapter.events()
    assert events
    for ev in events:
        assert ev.tags.get("confidence") == "low"
        assert ev.usd_estimate is not None and ev.usd_estimate > 0


def test_default_policy_is_unlimited(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch)
    policy = adapter.default_policy()
    assert policy.unit == Unit.USD
    assert policy.cycle == CycleKind.SLIDING_FROM_FIRST_USE
    assert policy.allowance is None

    runway = compute_runway(adapter.events(), policy)
    assert runway.status == Status.UNLIMITED


def test_missing_root_not_available(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTINUE_GLOBAL_DIR", str(tmp_path / "nope"))
    adapter = ContinueAdapter()
    assert not adapter.available()
    assert list(adapter.scan()) == []
