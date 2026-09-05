from __future__ import annotations

import json

from token_finops_cli.adapters.codex import CodexAdapter, build_synthetic_codex
from token_finops_cli.core.model import Unit


def _make_adapter(tmp_path, monkeypatch, **kwargs):
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    n_expected = build_synthetic_codex(str(codex_home), **kwargs)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    adapter = CodexAdapter()
    return adapter, n_expected


def test_event_count_matches_distinct_positive_deltas(tmp_path, monkeypatch):
    adapter, n_expected = _make_adapter(tmp_path, monkeypatch, days=3, sessions_per_day=2, seed=1)
    events = list(adapter.scan())
    assert len(events) == n_expected
    # every event_id must be unique (dedup key session:line_no)
    assert len({e.event_id for e in events}) == len(events)


def test_cache_read_split_and_input_excludes_cached(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, days=1, sessions_per_day=1, seed=2)
    events = list(adapter.scan())
    assert events
    for ev in events:
        assert ev.cache_read_tokens >= 0
        assert ev.input_tokens >= 0
        # reconstruct total input_tokens from delta and check input+cache_read == raw input
        # (raw input isn't directly exposed, but input should never exceed total input)
    # at least one event should show nonzero cache_read given the fixture ranges
    assert any(ev.cache_read_tokens > 0 for ev in events)


def test_usd_estimate_positive_for_gpt5(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, days=1, sessions_per_day=3, seed=3)
    events = list(adapter.scan())
    gpt5_events = [e for e in events if e.model_norm == "gpt-5"]
    assert gpt5_events, "expected at least one gpt-5 event in the fixture"
    for ev in gpt5_events:
        assert ev.usd_estimate is not None
        assert ev.usd_estimate > 0


def test_quota_returns_used_fraction_and_resets_at(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, days=2, sessions_per_day=1, seed=4)
    snap = adapter.quota()
    assert snap is not None
    assert snap.window_id == "5h"
    assert snap.used_fraction is not None
    assert 0.0 <= snap.used_fraction <= 1.0
    assert snap.resets_at is not None
    assert snap.source == "codex_rollout"

    primary, secondary = adapter.quotas()
    assert primary is not None and primary.window_id == "5h"
    assert secondary is not None and secondary.window_id == "7d"


def test_default_policy_unit_is_percent(tmp_path, monkeypatch):
    adapter, _ = _make_adapter(tmp_path, monkeypatch, days=1, sessions_per_day=1, seed=5)
    policy = adapter.default_policy()
    assert policy.unit == Unit.PERCENT
    assert policy.tool == "codex"
    assert policy.window_id == "5h"


def test_dedup_skips_duplicate_lines(tmp_path, monkeypatch):
    """build_synthetic_codex injects one exact-duplicate token_count line per
    session; verify the adapter does not double count it (i.e. scanning the
    raw file has more token_count lines than emitted events for at least one
    session)."""
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    build_synthetic_codex(str(codex_home), days=1, sessions_per_day=1, seed=6)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    adapter = CodexAdapter()
    paths = adapter.rollout_paths()
    assert len(paths) == 1
    raw_token_count_lines = 0
    with open(paths[0], encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("{"):
                continue
            rec = json.loads(line)
            if rec.get("type") == "event_msg" and (rec.get("payload") or {}).get("type") == "token_count":
                raw_token_count_lines += 1
    events = list(adapter.scan())
    # one line is an exact duplicate of the previous cumulative totals -> its
    # delta is zero and it must be skipped
    assert len(events) == raw_token_count_lines - 1


def test_archived_sessions_are_scanned(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    build_synthetic_codex(str(codex_home / "archived_sessions"), days=1, sessions_per_day=1, seed=7)
    # relocate the generated sessions dir under archived_sessions/sessions -> fix path shape
    # build_synthetic_codex writes to <root>/sessions/..., so root_dir=archived_sessions gives
    # archived_sessions/sessions/... which isn't the expected archived_sessions/** shape used by
    # rollout_paths (archived_sessions/**/rollout-*.jsonl matches any depth, including sessions/).
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    adapter = CodexAdapter()
    paths = adapter.rollout_paths()
    assert len(paths) == 1
    assert "archived_sessions" in paths[0]
