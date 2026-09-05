from __future__ import annotations

from token_finops_cli.adapters.gemini_cli import GeminiCliAdapter, build_synthetic_gemini
from token_finops_cli.core.model import CycleKind, Unit
from token_finops_cli.core.runway import compute_runway


def _make_adapter(tmp_path, monkeypatch, **kwargs):
    root = tmp_path / "gemini_home"
    monkeypatch.setenv("GEMINI_CLI_HOME", str(root))
    n_events = build_synthetic_gemini(str(root), **kwargs)
    adapter = GeminiCliAdapter()
    return adapter, n_events


def test_event_count_matches_gemini_messages(tmp_path, monkeypatch):
    adapter, n_expected = _make_adapter(tmp_path, monkeypatch, days=3, sessions_per_day=2, seed=1)
    events = adapter.events()
    assert len(events) == n_expected
    assert n_expected > 0


def test_cached_split_and_output_accounting(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, days=1, sessions_per_day=1, seed=7)
    events = adapter.events()
    assert events
    for ev in events:
        # cache_read == the raw "cached" value, and input excludes it.
        assert ev.cache_read_tokens >= 0
        assert ev.input_tokens >= 0
        # output_tokens for pricing = raw output + thoughts.
        assert ev.reasoning_tokens <= ev.output_tokens
        assert ev.reasoning_is_subset_of_output is False
        assert "thoughts" in ev.tags
        assert "tool_tokens" in ev.tags
        assert ev.tags["thoughts"] == ev.reasoning_tokens


def test_subagent_events_have_agent_id(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, days=2, sessions_per_day=2, seed=3)
    events = adapter.events()
    sub_events = [e for e in events if e.agent_id]
    assert sub_events, "expected at least one sub-agent event with agent_id set"
    for ev in sub_events:
        assert ev.initiator == "agent"
    main_events = [e for e in events if not e.agent_id]
    assert main_events
    for ev in main_events:
        assert ev.initiator == "user"


def test_usd_estimate_positive(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, days=1, sessions_per_day=1, seed=9)
    events = adapter.events()
    assert events
    assert all(ev.usd_estimate is not None and ev.usd_estimate > 0 for ev in events)


def test_default_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "gemini_home"))
    adapter = GeminiCliAdapter()
    policy = adapter.default_policy()
    assert policy.unit == Unit.REQUESTS
    assert policy.cycle == CycleKind.DAILY
    assert policy.allowance == 1000.0


def test_quota_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "gemini_home"))
    adapter = GeminiCliAdapter()
    assert adapter.quota() is None


def test_dedup_no_duplicate_event_ids(tmp_path, monkeypatch):
    adapter, n_expected = _make_adapter(tmp_path, monkeypatch, days=2, sessions_per_day=2, seed=5)
    events = adapter.events()
    ids = [ev.event_id for ev in events]
    assert len(ids) == len(set(ids))
    assert len(events) == n_expected


def test_compute_runway_used_equals_todays_events(tmp_path, monkeypatch):
    # days=1 -> all fixture events are timestamped "today" (within the last
    # ~59 minutes of now, per build_synthetic_gemini), so every event lands
    # in the DAILY window and the runway's "used" (REQUESTS => 1 per event)
    # equals the event count.
    adapter, n_expected = _make_adapter(tmp_path, monkeypatch, days=1, sessions_per_day=3, seed=11)
    events = adapter.events()
    policy = adapter.default_policy()
    runway = compute_runway(events, policy)
    assert runway.used == len(events)
    assert runway.used == n_expected
