import json
from datetime import datetime, timedelta, timezone

import pytest

from token_finops_cli import status as st


def payload(**over):
    base = [
        {"tool": "copilot", "display_name": "GitHub Copilot CLI", "window": "month", "unit": "aiu",
         "used_fraction": 0.294, "runway_days": 41.2, "status": "OK"},
        {"tool": "claude_code", "display_name": "Claude Code", "window": "5h", "unit": "percent",
         "used_fraction": 0.61, "runway_days": 0.08, "status": "WARN"},
        {"tool": "hermes", "display_name": "Hermes Agent", "window": "30d", "unit": "usd",
         "used_fraction": None, "runway_days": None, "status": "UNLIMITED"},
        {"tool": "gemini_cli", "display_name": "Gemini CLI", "window": "day", "unit": "requests",
         "used_fraction": 0.06, "runway_days": float("inf"), "status": "OK"},
    ]
    return base


def test_snapshot_binding_is_shortest_runway_and_ignores_unlimited():
    snap = st.build_snapshot(payload())
    assert snap["schema_version"] == st.SCHEMA_VERSION
    assert snap["binding"]["tool"] == "claude_code"


def test_plain_hides_unlimited_by_default_and_marks_binding():
    snap = st.build_snapshot(payload())
    out = st.render(snap, "plain")
    assert "HM" not in out and "CC 61% 2h!" in out and "binds: CC" in out
    assert "HM ? n/a" in st.render(snap, "plain", show_all=True)
    assert "GM 6% inf" in out


def test_every_format_renders_without_error():
    snap = st.build_snapshot(payload())
    for fmt in st.RENDERERS:
        out = st.render(snap, fmt)
        assert out and "Traceback" not in out


def test_tmux_and_polybar_carry_colours():
    snap = st.build_snapshot(payload())
    assert "#[fg=colour3]CC 61% 2h!#[default]" in st.render(snap, "tmux")
    assert "%{F#e5c07b}CC 61% 2h!%{F-}" in st.render(snap, "polybar")


def test_waybar_is_json_with_class_and_clamped_percentage():
    rows = payload()
    rows[1]["used_fraction"] = 1.6  # over-consumed
    snap = st.build_snapshot(rows)
    d = json.loads(st.render(snap, "waybar"))
    assert d["class"] == "warn" and d["percentage"] == 100 and "Claude Code" in d["tooltip"]


def test_starship_shows_binding_only():
    snap = st.build_snapshot(payload())
    assert st.render(snap, "starship") == "CC 61% 2h!"


def test_xbar_has_title_separator_and_refresh():
    out = st.render(st.build_snapshot(payload()), "xbar").splitlines()
    assert out[0].startswith("CC 2h!") and out[1] == "---" and out[-1] == "Refresh | refresh=true"


def test_cache_roundtrip_and_staleness(tmp_path):
    path = tmp_path / "last.json"
    snap = st.build_snapshot(payload())
    st.write_cache(snap, str(path))
    assert st.read_cache(str(path))["binding"]["tool"] == "claude_code"
    assert "CC 61% 2h!" in (tmp_path / "last.json.line").read_text()
    old = dict(snap, generated_at=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())
    assert 590 < st.stale_seconds(old) < 700
    assert st.read_cache(str(tmp_path / "missing.json")) is None
    path.write_text(json.dumps({"schema_version": 99}))
    assert st.read_cache(str(path)) is None


def test_json_format_is_strict_json_with_stale_seconds():
    snap = st.build_snapshot(payload())
    d = json.loads(st.render(snap, "json"))
    assert "stale_seconds" in d and d["tools"][0]["tool"] == "copilot"


@pytest.mark.parametrize("days,expect", [(None, "n/a"), (float("inf"), "inf"), (0.5, "12h"), (3.4, "3d")])
def test_fmt_runway(days, expect):
    assert st.fmt_runway(days) == expect


def test_cli_status_uses_cache_then_refreshes(home, run_cli, tmp_path, monkeypatch):
    from token_finops_cli.adapters.copilot import build_synthetic_db
    db = tmp_path / "s.db"
    build_synthetic_db(str(db), days=5, events_per_day=3)
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    cache = tmp_path / "cache.json"
    out1 = run_cli("status", "--fresh", "--budget", "5000", "--cache-file", str(cache))
    assert "CP" in out1 and cache.exists()
    # tamper with the cache: cached path must be served without rescanning
    snap = json.loads(cache.read_text())
    snap["tools"][0]["used_fraction"] = 0.123
    cache.write_text(json.dumps(snap))
    out2 = run_cli("status", "--max-age", "0", "--cache-file", str(cache))
    assert "12%" in out2
    out3 = run_cli("status", "--fresh", "--budget", "5000", "--cache-file", str(cache))
    assert "12%" not in out3
