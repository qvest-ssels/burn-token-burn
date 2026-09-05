from __future__ import annotations

from token_finops_cli.adapters.cline import ClineAdapter, build_synthetic_cline
from token_finops_cli.core.model import CycleKind, Unit


def _make_adapter(tmp_path, monkeypatch, **kwargs):
    root = tmp_path / "globalStorage"
    monkeypatch.setenv("TOKEN_FINOPS_CLINE_DIRS", str(root))
    n_events = build_synthetic_cline(str(root), **kwargs)
    adapter = ClineAdapter()
    return adapter, n_events


def test_event_count_matches_api_req_started_entries(tmp_path, monkeypatch):
    adapter, n_expected = _make_adapter(tmp_path, monkeypatch, tasks=6, seed=1)
    events = adapter.events()
    assert n_expected > 0
    assert len(events) == n_expected


def test_per_extension_tags(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, tasks=6, seed=2)
    events = adapter.events()
    assert events
    exts = {ev.tags.get("extension") for ev in events}
    assert exts == {"cline", "roo", "kilo"}
    for ev in events:
        assert ev.tags["extension"] in ("cline", "roo", "kilo")


def test_cost_passthrough_vs_estimate(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, tasks=6, seed=3)
    events = adapter.events()
    assert events
    # Every non-local event has a usd_estimate, whether from embedded cost or
    # from estimate_usd fallback (build_synthetic_cline omits cost for ~1/3
    # of the non-local tasks).
    non_local = [ev for ev in events if not ev.is_local_model]
    assert non_local
    assert all(ev.usd_estimate is not None and ev.usd_estimate > 0 for ev in non_local)


def test_local_model_flagged(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, tasks=6, seed=4)
    events = adapter.events()
    local_events = [ev for ev in events if ev.is_local_model]
    assert local_events, "expected at least one local-model task"
    for ev in local_events:
        assert ev.usd_estimate is None
        assert "ollama" in ev.model_raw


def test_default_policy_is_unbounded_usd(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_FINOPS_CLINE_DIRS", str(tmp_path / "globalStorage"))
    adapter = ClineAdapter()
    policy = adapter.default_policy()
    assert policy.unit == Unit.USD
    assert policy.cycle == CycleKind.SLIDING_FROM_FIRST_USE
    assert policy.allowance is None


def test_quota_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_FINOPS_CLINE_DIRS", str(tmp_path / "globalStorage"))
    adapter = ClineAdapter()
    assert adapter.quota() is None


def test_missing_root_not_available(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_FINOPS_CLINE_DIRS", str(tmp_path / "does-not-exist"))
    adapter = ClineAdapter()
    assert adapter.available() is False
    assert list(adapter.scan()) == []


def test_dedup_no_duplicate_event_ids(tmp_path, monkeypatch):
    adapter, n_expected = _make_adapter(tmp_path, monkeypatch, tasks=8, seed=5)
    events = adapter.events()
    ids = [ev.event_id for ev in events]
    assert len(ids) == len(set(ids))
    assert len(events) == n_expected


def test_session_id_is_task_id(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, tasks=4, seed=6)
    events = adapter.events()
    assert events
    for ev in events:
        assert ev.session_id.startswith("task-")
