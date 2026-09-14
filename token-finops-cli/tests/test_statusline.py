"""`token-finops collect-statusline`: persists Claude Code's statusLine JSON to
~/.token-finops and, after two snapshots, feeds a burn estimate into
`report --tool claude_code`."""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from conftest import transcript_line, write_transcript

from token_finops_cli import cli
from token_finops_cli.adapters.claude_code import ClaudeCodeAdapter
from token_finops_cli.cli import _ANSI_MODEL, _ANSI_OK, _ANSI_RESET


def _model(s):
    return f"{_ANSI_MODEL}{s}{_ANSI_RESET}"


def _win(label, pct):
    return f"{_ANSI_OK}{label} {pct:.0f}%{_ANSI_RESET}"


class _Clock:
    """Replaces cli.datetime so observed_at is deterministic."""

    def __init__(self, t: datetime):
        self.t = t

    def __call__(self):
        clock = self

        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.t if tz is None else clock.t.astimezone(tz)

        return FakeDT


@pytest.fixture
def clock(monkeypatch):
    c = _Clock(datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(cli, "datetime", c())
    return c


def collect(monkeypatch, run_cli, payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    return run_cli("collect-statusline")


def _payload(five=37.4, seven=12.0, resets=None, model="claude-opus-5"):
    rl = {"five_hour": {"used_percentage": five, "resets_at": resets}}
    if seven is not None:
        rl["seven_day"] = {"used_percentage": seven}
    return {"model": {"id": model, "display_name": "Opus"}, "rate_limits": rl,
            "cost": {"total_cost_usd": 1.5}}


def test_collect_writes_snapshot_and_history(home, run_cli, monkeypatch, clock):
    out = collect(monkeypatch, run_cli, _payload(resets="2026-09-15T15:00:00Z"))
    assert out == f"{_model('claude-opus-5')} | {_win('5h', 37)} | {_win('7d', 12)}\n"

    snap = json.loads((home / ".token-finops" / "quota.json").read_text())
    assert set(snap) == {"observed_at", "rate_limits", "model", "cost"}
    assert snap["observed_at"] == "2026-09-15T12:00:00+00:00"
    assert snap["model"] == "claude-opus-5" and snap["cost"] == {"total_cost_usd": 1.5}
    assert snap["rate_limits"]["five_hour"]["used_percentage"] == 37.4

    hist = (home / ".token-finops" / "quota_history.jsonl").read_text().splitlines()
    assert len(hist) == 1 and json.loads(hist[0]) == snap

    # second call: quota.json is replaced, history appended
    clock.t += timedelta(minutes=30)
    out = collect(monkeypatch, run_cli, _payload(five=41.0, seven=None, resets="2026-09-15T15:00:00Z"))
    assert out == f"{_model('claude-opus-5')} | {_win('5h', 41)}\n"
    snap2 = json.loads((home / ".token-finops" / "quota.json").read_text())
    assert snap2["rate_limits"]["five_hour"]["used_percentage"] == 41.0
    hist = (home / ".token-finops" / "quota_history.jsonl").read_text().splitlines()
    assert [json.loads(h)["observed_at"] for h in hist] == ["2026-09-15T12:00:00+00:00",
                                                            "2026-09-15T12:30:00+00:00"]

    # the adapter reads both files back
    ad = ClaudeCodeAdapter()
    q = ad.quota()
    assert q is not None and q.used_fraction == pytest.approx(0.41) and q.source == "claude_statusline"
    assert q.resets_at == datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)
    assert [h.used_fraction for h in ad.quota_history()] == [pytest.approx(0.374), pytest.approx(0.41)]
    assert ad.quota("seven_day") is None                # the latest payload carried no 7d window
    seven = ad.quota_history("seven_day")
    assert len(seven) == 1 and seven[0].window_id == "7d" and seven[0].used_fraction == pytest.approx(0.12)


def test_collect_without_rate_limits_writes_snapshot_but_no_history(home, run_cli, monkeypatch, clock):
    out = collect(monkeypatch, run_cli, {"model": {"id": "claude-sonnet-5"}})
    assert out == f"{_model('claude-sonnet-5')}\n"
    assert (home / ".token-finops" / "quota.json").exists()
    assert not (home / ".token-finops" / "quota_history.jsonl").exists()
    snap = json.loads((home / ".token-finops" / "quota.json").read_text())
    assert snap["rate_limits"] == {} and snap["cost"] is None
    assert ClaudeCodeAdapter().quota() is None


@pytest.mark.parametrize("raw", ["", "   \n", "{not json"])
def test_collect_tolerates_empty_or_invalid_stdin(home, run_cli, monkeypatch, clock, raw):
    out = collect(monkeypatch, run_cli, raw)
    assert out == "token-finops: no rate_limits in statusline payload\n"
    assert json.loads((home / ".token-finops" / "quota.json").read_text())["model"] is None


def test_collect_rate_limits_without_percentages(home, run_cli, monkeypatch, clock):
    out = collect(monkeypatch, run_cli, {"rate_limits": {"five_hour": {"resets_at": 1}}})
    assert out == "token-finops: no rate_limits in statusline payload\n"
    # the (useless) snapshot is still appended -- it carries no used_percentage, so the adapter drops it
    assert (home / ".token-finops" / "quota_history.jsonl").exists()
    assert ClaudeCodeAdapter().quota_history() == []


def test_snapshot_parsing_variants(home):
    snap = ClaudeCodeAdapter._snapshot
    base = {"observed_at": "2026-09-15T12:00:00+00:00"}
    assert snap({**base, "rate_limits": {"five_hour": {"used_percentage": 50, "resets_at": 1789000000}}}
                ).resets_at == datetime.fromtimestamp(1789000000, tz=timezone.utc)
    assert snap({**base, "rate_limits": {"five_hour": {"used_percentage": 50, "resets_at": "garbage"}}}
                ).resets_at is None
    assert snap({**base, "rate_limits": {"five_hour": {"used_percentage": 50}}}).resets_at is None
    assert snap({**base, "rate_limits": {}}) is None
    assert snap({}) is None
    s7 = snap({**base, "rate_limits": {"seven_day": {"used_percentage": 5}}}, "seven_day")
    assert s7.window_id == "7d" and s7.used_fraction == 0.05
    # observed_at missing -> now-ish
    s = snap({"rate_limits": {"five_hour": {"used_percentage": 1}}})
    assert abs((s.observed_at - datetime.now(timezone.utc)).total_seconds()) < 5


def test_quota_history_ignores_broken_lines_and_missing_file(home):
    ad = ClaudeCodeAdapter()
    assert ad.quota_history() == []
    d = home / ".token-finops"
    d.mkdir()
    (d / "quota_history.jsonl").write_text(
        'not json\n{"observed_at":"2026-09-15T12:00:00+00:00","rate_limits":{"five_hour":{"used_percentage":10}}}\n'
        '{"observed_at":"2026-09-15T12:10:00+00:00","rate_limits":{}}\n', encoding="utf-8")
    hist = ad.quota_history()
    assert len(hist) == 1 and hist[0].used_fraction == pytest.approx(0.1)
    (d / "quota.json").write_text("{broken", encoding="utf-8")
    assert ad.quota() is None


# --------------------------------------------------------------------------- #
# round trip: two statusline snapshots -> burn + runway in `report`
# --------------------------------------------------------------------------- #
def test_two_snapshots_yield_burn_and_runway_in_report(home, run_cli, monkeypatch, clock):
    cfg = home / ".claude"
    real_now = datetime.now(timezone.utc)
    write_transcript(cfg / "projects" / "p" / "s.jsonl", [
        transcript_line(real_now - timedelta(minutes=10), "m1", "r1", tool="Bash", session="s"),
    ])
    resets = (real_now + timedelta(hours=3)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # one snapshot: status known, no burn yet
    clock.t = real_now - timedelta(hours=1)
    collect(monkeypatch, run_cli, _payload(five=20.0, resets=resets))
    out = run_cli("report", "--tool", "claude_code")
    assert "Claude Code (last 7d):" in out
    assert "  calls:            1" in out
    assert "  used:     20% of the 5h window" in out
    assert "  burn:" not in out
    assert "  runway:   n/a -> OK" in out
    assert "needs >=2 snapshots" in out

    # second snapshot 30 min later, +10 %: 20 %/h burn, 4 h of runway vs 3 h left -> OK
    clock.t = real_now - timedelta(minutes=30)
    collect(monkeypatch, run_cli, _payload(five=30.0, resets=resets))
    out = run_cli("report", "--tool", "claude_code")
    assert "  used:     30% of the 5h window" in out
    assert "  burn:     20.0% per hour (from snapshots)" in out
    runway = next(ln for ln in out.splitlines() if ln.startswith("  runway:"))
    assert runway.startswith("  runway:   3.5h vs 3.0h left -> OK")
    assert "needs >=2 snapshots" not in out
    assert "%%" not in out and "% %" not in out

    data = json.loads(run_cli("report", "--tool", "claude_code", "--json"))
    assert data[0]["tool"] == "claude_code" and data[0]["unit"] == "percent"
    assert data[0]["used_fraction"] == pytest.approx(0.30)
    assert data[0]["burn_per_day_avg"] == pytest.approx(0.2 * 24)
    assert data[0]["runway_days"] == pytest.approx(3.5 / 24, rel=1e-3)
    assert data[0]["status"] == "OK" and data[0]["burn_per_day_ema"] is None

    # a third snapshot racing towards the limit flips the status to CRITICAL
    clock.t = real_now - timedelta(minutes=1)
    collect(monkeypatch, run_cli, _payload(five=80.0, resets=resets))
    out = run_cli("report", "--tool", "claude_code", "--compact")
    assert out.count("\n") == 1 and out.rstrip().endswith("CRIT")
