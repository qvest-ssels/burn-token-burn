"""End-user use cases, as a table.

Every row is one realistic thing a person does with `token-finops`: a plan
holder checking their Copilot budget mid-month, a Claude Code subscriber who
has not wired the status-line collector yet, a Gemini free-tier user at noon,
someone asking whether a Mac Studio would have been cheaper. Each row names
the persona, the setup, the command (or API call) and the expected,
user-visible outcome, and carries the assertion that proves it.

One parametrised test function per category, so a failure reads like a spec:

    FAILED tests/test_usecases.py::test_copilot_plans[UC-02] ...

`docs/USECASES.md` is generated from the same table:

    cd token-finops-cli && PYTHONPATH=src python3 tests/test_usecases.py --markdown > ../docs/USECASES.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable

import pytest
from conftest import (NOW, build_claude_tree, make_event, month_policy, percent_policy, transcript_line,
                      write_copilot_db, write_transcript)

from token_finops_cli.adapters.claude_code import ClaudeCodeAdapter
from token_finops_cli.adapters.cline import ClineAdapter, build_synthetic_cline
from token_finops_cli.adapters.codex import CodexAdapter, build_synthetic_codex
from token_finops_cli.adapters.gemini_cli import GeminiCliAdapter, build_synthetic_gemini
from token_finops_cli.adapters.hermes import HermesAdapter, build_synthetic_hermes
from token_finops_cli.core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Status, Unit
from token_finops_cli.core.runway import binding_constraint, compute_runway
from token_finops_cli.report import by_model
from token_finops_cli.savings import LocalCost, cloud_blended_usd_per_mtok, cmd_break_even, cmd_savings
from token_finops_cli.synth import generate

UTC = timezone.utc
REAL_NOW = datetime.now(UTC)


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class UseCase:
    """One named end-user scenario, its command and its expected outcome."""

    id: str
    persona: str
    title: str
    setup: str
    command: str
    expected: str
    check: Callable[["Ctx"], None]

    def __str__(self) -> str:  # pragma: no cover - only for failure output
        return f"{self.id} {self.title}"


@dataclass
class Ctx:
    """Fixtures a use case may need: an isolated HOME and an in-process CLI."""

    home: object
    tmp_path: object
    monkeypatch: object
    run_cli: Callable[..., str]

    def json_report(self, *argv: str) -> list[dict]:
        return json.loads(self.run_cli("report", "--json", *argv))

    def synth(self, tools: list[str], **kw) -> dict:
        """Write a synthetic fake-home tree *into the isolated HOME*, where
        every adapter's default root already points (see conftest.home)."""
        return generate(str(self.home), tools=tools, **kw)


ALL_CASES: list[UseCase] = []


def uc(case: UseCase) -> UseCase:
    ALL_CASES.append(case)
    return case


@pytest.fixture
def ctx(home, tmp_path, monkeypatch, run_cli) -> Ctx:
    return Ctx(home=home, tmp_path=tmp_path, monkeypatch=monkeypatch, run_cli=run_cli)


def _ids(case: UseCase) -> str:
    return case.id


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _copilot_db(ctx: Ctx, rows: list[dict]):
    db = ctx.home / "copilot.db"
    write_copilot_db(db, rows)
    ctx.monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    return db


def _aiu_rows(n: int, aiu: float, session: str = "s1") -> list[dict]:
    """`n` Copilot calls of `aiu` AI units each, just now (i.e. inside the
    current billing cycle whenever the suite happens to run)."""
    return [{"ts": REAL_NOW - timedelta(seconds=i), "session": session,
             "inp": 1000, "out": 200, "nano_aiu": int(aiu * 1e9)} for i in range(n)]


def _write_quota(ctx: Ctx, snapshots: list[tuple[datetime, float, datetime]]) -> None:
    """Write what `token-finops collect-statusline` would have written."""
    qdir = ctx.home / ".token-finops"
    qdir.mkdir(parents=True, exist_ok=True)
    lines = []
    for observed_at, used_pct, resets_at in snapshots:
        lines.append(json.dumps({
            "observed_at": observed_at.isoformat(),
            "rate_limits": {"five_hour": {"used_percentage": used_pct,
                                          "resets_at": resets_at.isoformat()}},
            "model": "claude-fable-5-1",
        }))
    (qdir / "quota_history.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (qdir / "quota.json").write_text(lines[-1], encoding="utf-8")


def _claude_home(ctx: Ctx, now: datetime = None):
    return build_claude_tree(ctx.home / ".claude", now=now or REAL_NOW)


def _codex_rollout(ctx: Ctx, totals: list[dict], *, model: str = "gpt-5",
                   rate_limits: dict = None, duplicate_last: bool = False):
    """Hand-written Codex rollout file with explicit cumulative counters."""
    root = ctx.home / ".codex"
    day = REAL_NOW
    d = root / "sessions" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "rollout-usecase.jsonl"
    lines = [json.dumps({"type": "session_meta", "payload": {"id": "sess-uc", "cwd": "/w"}}),
             json.dumps({"type": "turn_context", "payload": {"model": model}})]

    def token_count(total: dict) -> str:
        payload = {"type": "token_count", "info": {"total_token_usage": total}}
        if rate_limits:
            payload["rate_limits"] = rate_limits
        return json.dumps({"type": "event_msg", "timestamp": day.isoformat(), "payload": payload})

    for total in totals:
        lines.append(token_count(total))
    if duplicate_last and totals:
        lines.append(token_count(totals[-1]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ctx.monkeypatch.setenv("CODEX_HOME", str(root))
    return CodexAdapter()


def _savings_args(**kw) -> SimpleNamespace:
    base = dict(hardware="mac-studio-m4-max-128gb", model="qwen3-32b", power="grid-de-household",
                utilization=0.2, lifetime_years=3.0, output_share=0.15, list=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _break_even_args(**kw) -> SimpleNamespace:
    base = dict(hardware="mac-studio-m4-max-128gb", model="qwen3-32b", power="grid-de-household",
                lifetime_years=3.0, replaceable_tiers="haiku,sonnet", tool=None, since="all")
    base.update(kw)
    return SimpleNamespace(**base)


def _sonnet_session(ctx: Ctx, calls: int, *, out: int, cr: int = 0, cw: int = 0,
                    model: str = "claude-sonnet-5") -> None:
    """A Claude Code transcript with `calls` priced calls of a known size."""
    proj = ctx.home / ".claude" / "projects" / "-home-x"
    write_transcript(proj / "sess-be.jsonl", [
        transcript_line(REAL_NOW - timedelta(minutes=calls - i), f"m{i}", f"r{i}", model=model,
                        session="sess-be", inp=100, out=out, cr=cr, cw=cw)
        for i in range(calls)
    ])


# =========================================================================== #
# Category 1: GitHub Copilot CLI plan holders (AI units, calendar month, UTC)
# =========================================================================== #
def _c01(ctx: Ctx) -> None:
    events = [make_event(days_ago=d, now=NOW, aiu=45.0) for d in range(15)]
    r = compute_runway(events, month_policy(1500.0), now=NOW)
    assert r.used == pytest.approx(675.0)
    assert r.used_fraction == pytest.approx(0.45, abs=0.01)
    assert r.pace_ratio < 1.0
    assert r.runway_days > r.days_left
    assert r.status is Status.OK


def _c02(ctx: Ctx) -> None:
    quiet = [make_event(days_ago=d, now=NOW, aiu=100.0) for d in range(2, 15)]
    burst = [make_event(days_ago=d, now=NOW, aiu=2000.0) for d in (0, 1)]
    r = compute_runway(quiet + burst, month_policy(7000.0), now=NOW)
    assert r.burn_per_day_ema > r.burn_per_day_avg   # yesterday's burst is visible immediately
    assert r.runway_days < r.days_left
    assert r.status is Status.CRITICAL


def _c03(ctx: Ctx) -> None:
    events = [make_event(days_ago=d, now=NOW, aiu=1400.0) for d in range(15)]
    r = compute_runway(events, month_policy(20_000.0), now=NOW)
    assert r.used == pytest.approx(21_000.0)
    assert r.used_fraction > 1.0
    assert r.runway_days == 0.0
    assert r.status is Status.EXHAUSTED


def _c04(ctx: Ctx) -> None:
    now = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    r = compute_runway([make_event(days_ago=0.125, now=now, aiu=5.0)], month_policy(1900.0), now=now)
    assert r.window_start == datetime(2026, 10, 1, tzinfo=UTC)
    assert r.resets_at == datetime(2026, 11, 1, tzinfo=UTC)
    assert r.time_fraction < 0.01
    assert r.status is Status.OK


def _c05(ctx: Ctx) -> None:
    _copilot_db(ctx, _aiu_rows(6, 100.0))
    d = ctx.json_report("--budget", "3900", "--cycle-day", "15")[0]
    assert d["allowance"] == 3900.0
    assert d["used"] == pytest.approx(600.0)
    assert d["resets_at"].endswith("-15 00:00:00+00:00")     # cycle rolls on the 15th


def _c06(ctx: Ctx) -> None:
    now = datetime(2026, 12, 20, 12, 0, tzinfo=UTC)
    events = [make_event(days_ago=d, now=now, aiu=100.0) for d in range(19)]
    r = compute_runway(events, month_policy(7000.0), now=now)
    assert r.window_start == datetime(2026, 12, 1, tzinfo=UTC)
    assert r.resets_at == datetime(2027, 1, 1, tzinfo=UTC)   # year rollover, not month 13
    assert r.days_left == pytest.approx(11.5, abs=0.01)


def _c07(ctx: Ctx) -> None:
    _copilot_db(ctx, _aiu_rows(6, 100.0))
    out = ctx.run_cli("report", "--budget", "1500")
    assert "GitHub Copilot CLI" in out
    assert "600.0 / 1,500.0 AI units" in out
    assert "runway:" in out


def _c08(ctx: Ctx) -> None:
    _copilot_db(ctx, _aiu_rows(20, 100.0))
    out = ctx.run_cli("report", "--budget", "1500", "--compact")
    assert out.strip().count("\n") == 0          # exactly one line for the one tool
    assert "100.0%" in out and "OUT" in out


def _c09(ctx: Ctx) -> None:
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    events = [make_event(days_ago=d, now=now, aiu=1140.0 / 23) for d in range(23)]
    r = compute_runway(events, month_policy(1500.0), now=now)
    assert r.used_fraction == pytest.approx(0.76, abs=0.005)
    assert r.runway_days > r.days_left            # still makes it to the reset
    assert r.status is Status.WARN


COPILOT_CASES = [
    uc(UseCase("UC-01", "Copilot Pro (1500 AIU)", "Mid-month, on pace",
               "15 days into the September cycle, 45 AI units burned per day",
               "token-finops report --budget 1500",
               "used 675/1500 (45 %), pace < 1.0, runway outlasts the reset -> OK", _c01)),
    uc(UseCase("UC-02", "Copilot Pro+ (7000 AIU)", "Burst yesterday",
               "Two quiet weeks at 100 AIU/day, then two days at 2000 AIU/day",
               "token-finops report --budget 7000",
               "EMA burn exceeds the cycle average, runway shorter than the days left -> CRITICAL",
               _c02)),
    uc(UseCase("UC-03", "Copilot Max (20000 AIU)", "Allowance exhausted",
               "15 days at 1400 AIU/day = 21,000 AIU against a 20,000 allowance",
               "token-finops report --budget 20000",
               "used > 100 %, runway 0 days -> EXHAUSTED", _c03)),
    uc(UseCase("UC-04", "Copilot Business (1900 AIU)", "Fresh cycle, day 1",
               "First morning of the new cycle (1 Oct, 06:00 UTC), one small call",
               "token-finops report --budget 1900",
               "window starts 1 Oct, resets 1 Nov, < 1 % of the window elapsed -> OK", _c04)),
    uc(UseCase("UC-05", "Copilot Enterprise (3900 AIU)", "Contract resets on the 15th",
               "Enterprise contract whose billing cycle does not start on the 1st",
               "token-finops report --budget 3900 --cycle-day 15",
               "resets_at falls on the 15th, 600 AIU counted in the current cycle", _c05)),
    uc(UseCase("UC-06", "Copilot Pro+ (7000 AIU)", "Year rollover in December",
               "20 December, 19 days of usage in the December cycle",
               "token-finops report --budget 7000",
               "next reset is 2027-01-01 (not month 13), 11.5 days left", _c06)),
    uc(UseCase("UC-07", "Copilot Pro (1500 AIU)", "Plain text report",
               "Six calls at 100 AI units each in the current cycle",
               "token-finops report --budget 1500",
               "report prints 'GitHub Copilot CLI' and 'used: 600.0 / 1,500.0 AI units'", _c07)),
    uc(UseCase("UC-08", "Copilot Pro (1500 AIU)", "Compact one-liner when out of budget",
               "2000 AI units burned against a 1500 allowance",
               "token-finops report --budget 1500 --compact",
               "exactly one line, showing 100.0 % and the OUT marker", _c08)),
    uc(UseCase("UC-09", "Copilot Pro (1500 AIU)", "Warning, but will still make it",
               "Even burn, 76 % used on the 24th of the month",
               "token-finops report --budget 1500",
               "runway (7.4 d) still exceeds the 6.5 days left -> WARN, not CRITICAL", _c09)),
]


# =========================================================================== #
# Category 2: Claude Code subscribers (opaque provider %, rolling 5h window)
# =========================================================================== #
def _cc10(ctx: Ctx) -> None:
    _claude_home(ctx)
    out = ctx.run_cli("report", "--tool", "claude_code")
    assert "UNKNOWN" in out
    assert "collect-statusline" in out            # the report tells you how to fix it


def _cc11(ctx: Ctx) -> None:
    _claude_home(ctx)
    _write_quota(ctx, [(REAL_NOW, 30.0, REAL_NOW + timedelta(hours=3))])
    out = ctx.run_cli("report", "--tool", "claude_code")
    assert "30% of the 5h window" in out
    assert "no burn estimate yet: needs >=2 snapshots" in out


def _cc12(ctx: Ctx) -> None:
    _claude_home(ctx)
    reset = REAL_NOW + timedelta(hours=3)
    _write_quota(ctx, [(REAL_NOW - timedelta(hours=1), 20.0, reset), (REAL_NOW, 30.0, reset)])
    d = ctx.json_report("--tool", "claude_code")[0]
    assert d["used_fraction"] == pytest.approx(0.30)
    assert d["burn_per_day_avg"] == pytest.approx(2.4, rel=0.05)     # 10 %/h == 2.4 windows/day
    assert d["runway_days"] > d["days_left"]
    assert d["status"] == "OK"


def _cc13(ctx: Ctx) -> None:
    _claude_home(ctx)
    reset = REAL_NOW + timedelta(hours=3)
    _write_quota(ctx, [(REAL_NOW - timedelta(hours=1), 40.0, reset), (REAL_NOW, 80.0, reset)])
    d = ctx.json_report("--tool", "claude_code")[0]
    assert d["used_fraction"] == pytest.approx(0.80)
    assert d["runway_days"] < d["days_left"]      # 20 % left at 40 %/h -> half an hour
    assert d["status"] == "CRITICAL"


def _cc14(ctx: Ctx) -> None:
    stale = QuotaSnapshot(tool="claude_code", window_id="5h", observed_at=NOW - timedelta(hours=8),
                          used_fraction=0.92, resets_at=NOW - timedelta(hours=3),
                          source="claude_statusline")
    r = compute_runway([], percent_policy(), now=NOW, quota=stale)
    assert r.resets_at is None                    # the window it described has already reset
    assert r.days_left is None and r.time_fraction is None
    assert r.status is Status.CRITICAL


def _cc15(ctx: Ctx) -> None:
    _claude_home(ctx)
    out = ctx.run_cli("self-audit")
    assert "main loop 8 + sub-agents 3" in out
    assert "sub-agents = 29% of API-equivalent cost" in out


def _cc16(ctx: Ctx) -> None:
    _claude_home(ctx)
    main = ctx.home / ".claude" / "projects" / "-home-x" / "sess-1.jsonl"
    raw_lines = [ln for ln in main.read_text(encoding="utf-8").splitlines() if '"usage"' in ln]
    events = ClaudeCodeAdapter(str(ctx.home / ".claude" / "projects")).events()
    assert len(raw_lines) == 10                   # content-block lines on disk
    assert len([e for e in events if not e.agent_id]) == 8      # deduplicated API calls
    assert len(events) == 11


def _cc17(ctx: Ctx) -> None:
    proj = ctx.home / ".claude" / "projects" / "-home-x"
    write_transcript(proj / "sess-mix.jsonl", [
        transcript_line(REAL_NOW, "f1", "fr1", model="claude-fable-5-1", session="sess-mix"),
    ])
    write_transcript(proj / "sess-mix" / "subagents" / "agent-haiku.jsonl", [
        transcript_line(REAL_NOW, "h1", "hr1", model="claude-haiku-4-5", agent="haiku",
                        session="sess-mix"),
    ])
    rows = dict(by_model(ClaudeCodeAdapter(str(ctx.home / ".claude" / "projects")).events()))
    assert set(rows) == {"claude-fable-5-1", "claude-haiku-4-5"}
    # identical token counts: Fable ($10/$50 per MTok) costs exactly 10x Haiku ($1/$5)
    assert rows["claude-fable-5-1"]["usd"] == pytest.approx(10 * rows["claude-haiku-4-5"]["usd"])


def _cc18(ctx: Ctx) -> None:
    _claude_home(ctx)
    d = json.loads(ctx.run_cli("self-audit", "--json"))
    assert (d["calls"], d["main"], d["subagents"]) == (11, 8, 3)
    assert set(d["by_model"]) == {"claude-sonnet-5", "claude-haiku-4-5"}


CLAUDE_CASES = [
    uc(UseCase("UC-10", "Claude Code subscriber", "No status-line snapshot yet",
               "Transcripts on disk, but `collect-statusline` never wired up",
               "token-finops report --tool claude_code",
               "status UNKNOWN plus a note telling you to wire collect-statusline", _cc10)),
    uc(UseCase("UC-11", "Claude Code subscriber", "First snapshot, no burn yet",
               "One status-line snapshot: 30 % of the 5h window used",
               "token-finops report --tool claude_code",
               "'30% of the 5h window' and 'no burn estimate yet: needs >=2 snapshots'", _cc11)),
    uc(UseCase("UC-12", "Claude Code subscriber", "Two snapshots, comfortable pace",
               "20 % -> 30 % of the 5h window over one hour, resets in 3 h",
               "token-finops report --tool claude_code --json",
               "burn ~10 %/h, runway longer than the time to reset -> OK", _cc12)),
    uc(UseCase("UC-13", "Claude Code subscriber", "Two snapshots, burning fast",
               "40 % -> 80 % of the 5h window over one hour, resets in 3 h",
               "token-finops report --tool claude_code --json",
               "runway (~0.5 h) far shorter than the 3 h to reset -> CRITICAL", _cc13)),
    uc(UseCase("UC-14", "Claude Code subscriber", "Stale snapshot from a past window",
               "Latest snapshot says 92 %, but its window reset three hours ago",
               "compute_runway(events, policy, quota=stale_snapshot)",
               "resets_at/days_left dropped (window already reset), status from used% -> CRITICAL",
               _cc14)),
    uc(UseCase("UC-15", "Claude Code power user", "Sub-agent heavy session self-audit",
               "One session: 8 main-loop calls plus 3 sub-agent calls (Haiku + Sonnet)",
               "token-finops self-audit",
               "'main loop 8 + sub-agents 3' and 'sub-agents = 29% of API-equivalent cost'", _cc15)),
    uc(UseCase("UC-16", "Claude Code subscriber", "Content-block lines deduplicated",
               "Transcript writes one line per content block of the same API response",
               "ClaudeCodeAdapter(...).events()",
               "10 usage lines on disk collapse to 8 main-loop calls (11 incl. sub-agents)", _cc16)),
    uc(UseCase("UC-17", "Claude Code power user", "Haiku vs Fable cost split",
               "Fable main loop plus a Haiku sub-agent, identical token counts",
               "by_model(adapter.events())",
               "both models listed; Fable costs exactly 10x the Haiku call", _cc17)),
    uc(UseCase("UC-18", "Claude Code power user", "Machine-readable self-audit",
               "Same session as UC-15, piped into jq",
               "token-finops self-audit --json",
               "{'calls': 11, 'main': 8, 'subagents': 3} and both models in by_model", _cc18)),
]


# =========================================================================== #
# Category 3: OpenAI Codex CLI (rate_limits in the rollout JSONL)
# =========================================================================== #
def _cx19(ctx: Ctx) -> None:
    root = ctx.home / ".codex"
    build_synthetic_codex(str(root), days=2, sessions_per_day=1, seed=11, scenario="exhausted")
    ctx.monkeypatch.setenv("CODEX_HOME", str(root))
    snap = CodexAdapter().quota()
    assert snap is not None and snap.used_fraction >= 0.95
    out = ctx.run_cli("report", "--tool", "codex", "--compact")
    assert "CRIT" in out or "OUT" in out


def _cx20(ctx: Ctx) -> None:
    root = ctx.home / ".codex"
    build_synthetic_codex(str(root), days=2, sessions_per_day=1, seed=12)
    ctx.monkeypatch.setenv("CODEX_HOME", str(root))
    primary, secondary = CodexAdapter().quotas()
    assert primary.window_id == "5h" and secondary.window_id == "7d"
    assert 0.0 <= secondary.used_fraction <= 1.0
    assert secondary.source == "codex_rollout"
    assert secondary.resets_at is not None


def _cx21(ctx: Ctx) -> None:
    adapter = _codex_rollout(ctx, [
        {"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 200,
         "cache_write_input_tokens": 0, "reasoning_output_tokens": 50},
        {"input_tokens": 2500, "cached_input_tokens": 1000, "output_tokens": 500,
         "cache_write_input_tokens": 0, "reasoning_output_tokens": 120},
    ])
    events = adapter.events()
    assert len(events) == 2
    second = events[-1]
    assert second.cache_read_tokens == 600                     # delta of cached_input_tokens
    assert second.input_tokens == 900                          # 1500 raw input - 600 cached
    assert second.output_tokens == 300


def _cx22(ctx: Ctx) -> None:
    adapter = _codex_rollout(ctx, [
        {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 200,
         "cache_write_input_tokens": 0, "reasoning_output_tokens": 0},
        {"input_tokens": 3000, "cached_input_tokens": 0, "output_tokens": 700,
         "cache_write_input_tokens": 0, "reasoning_output_tokens": 0},
    ], duplicate_last=True)
    events = adapter.events()
    assert len(events) == 2                                    # the repeated total is a zero delta
    assert sum(e.input_tokens + e.output_tokens for e in events) == 3700


CODEX_CASES = [
    uc(UseCase("UC-19", "Codex CLI (ChatGPT plan)", "Primary window at 95 %",
               "Rollout files whose rate_limits.primary is pinned at 95-100 %",
               "token-finops report --tool codex --compact",
               "provider snapshot >= 95 % used -> CRIT/OUT in the compact line", _cx19)),
    uc(UseCase("UC-20", "Codex CLI (ChatGPT plan)", "Weekly secondary window",
               "Same rollout files, reading the secondary (7d) rate limit",
               "CodexAdapter().quotas()",
               "secondary snapshot has window_id '7d', a 0..1 fraction and a reset time", _cx20)),
    uc(UseCase("UC-21", "Codex CLI user", "Cached input tokens are not double counted",
               "Cumulative token_count rows: input 1000->2500 of which cached 400->1000",
               "CodexAdapter().events()",
               "cache_read = 600, input = 900 (1500 raw - 600 cached), output = 300", _cx21)),
    uc(UseCase("UC-22", "Codex CLI user", "Duplicate token_count heartbeat",
               "The CLI repeats the last cumulative totals on a heartbeat line",
               "CodexAdapter().events()",
               "the zero-delta duplicate is skipped: 2 events, 3700 tokens", _cx22)),
]


# =========================================================================== #
# Category 4: Gemini CLI (free tier: requests per day)
# =========================================================================== #
def _g23(ctx: Ctx) -> None:
    policy = GeminiCliAdapter().default_policy()
    assert policy.unit is Unit.REQUESTS and policy.allowance == 1000.0
    noon = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    events = [make_event(days_ago=i / 1440.0, now=noon, tool="gemini_cli", model="gemini-2.5-pro",
                         aiu=None, native_unit=None) for i in range(600)]
    r = compute_runway(events, policy, now=noon)
    assert r.used == 600.0 and r.used_fraction == pytest.approx(0.6)
    assert r.time_fraction == pytest.approx(0.5)
    assert r.pace_ratio == pytest.approx(1.2)     # 20 % faster than the day is passing
    assert r.status is Status.CRITICAL


def _g24(ctx: Ctx) -> None:
    root = ctx.home / ".gemini"
    build_synthetic_gemini(str(root), days=2, sessions_per_day=2, seed=3)
    ctx.monkeypatch.setenv("GEMINI_CLI_HOME", str(root))
    events = GeminiCliAdapter().events()
    subs = [e for e in events if e.agent_id]
    assert subs, "sub-agent chats live in chats/<parentSessionId>/ and must be counted"
    assert all(e.initiator == "agent" for e in subs)
    assert len(events) > len([e for e in events if not e.agent_id])


def _g25(ctx: Ctx) -> None:
    noon = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    sizes = [(100, 50), (200_000, 40_000), (900, 10)]
    events = [make_event(days_ago=0.1, now=noon, tool="gemini_cli", model="gemini-2.5-flash",
                         aiu=None, native_unit=None, inp=i, out=o) for i, o in sizes]
    r = compute_runway(events, GeminiCliAdapter().default_policy(), now=noon)
    assert r.unit is Unit.REQUESTS
    assert r.used == 3.0                          # a 200k-token call still costs one request
    assert r.used_fraction == pytest.approx(0.003)


GEMINI_CASES = [
    uc(UseCase("UC-23", "Gemini CLI free tier", "600 of 1000 requests by noon",
               "Free tier: 1000 requests/day; 600 already used at 12:00 UTC",
               "token-finops report --tool gemini_cli",
               "pace 1.2x (60 % of quota, 50 % of the day) and runway < the rest of the day -> CRITICAL",
               _g23)),
    uc(UseCase("UC-24", "Gemini CLI user", "Sub-agent chats counted too",
               "Sub-agent transcripts nested under chats/<parentSessionId>/",
               "GeminiCliAdapter().events()",
               "sub-agent events carry agent_id, initiator 'agent', and add to the day's requests",
               _g24)),
    uc(UseCase("UC-25", "Gemini CLI free tier", "Requests, not tokens, are the budget",
               "Three calls of wildly different sizes (100 to 240k tokens)",
               "compute_runway(events, gemini_policy)",
               "used == 3.0 requests regardless of token size (0.3 % of the daily quota)", _g25)),
]


# =========================================================================== #
# Category 5: Hermes Agent (OpenRouter USD + local Ollama)
# =========================================================================== #
def _h26(ctx: Ctx) -> None:
    root = ctx.home / ".hermes"
    build_synthetic_hermes(str(root), sessions=12, seed=1)
    ctx.monkeypatch.setenv("HERMES_HOME", str(root))
    openrouter = [e for e in HermesAdapter().events() if e.native_unit is Unit.USD]
    assert openrouter, "OpenRouter rows are billed in USD natively"
    for e in openrouter:
        assert e.native_cost > 0
        assert e.usd_estimate == pytest.approx(e.native_cost)


def _h27(ctx: Ctx) -> None:
    root = ctx.home / ".hermes"
    build_synthetic_hermes(str(root), sessions=12, seed=1)
    ctx.monkeypatch.setenv("HERMES_HOME", str(root))
    local = [e for e in HermesAdapter().events() if e.is_local_model]
    assert local, "expected local Ollama rows in the fixture"
    for e in local:
        assert e.usd_estimate is None and e.native_cost is None
        assert e.total_tokens > 0                 # tokens are still counted, they just cost nothing


def _h28(ctx: Ctx) -> None:
    ctx.synth(["hermes"], days=10, seed=4)
    out = ctx.run_cli("report", "--tool", "hermes", "--compact")
    assert "Hermes Agent" in out and "inf" in out  # usage-only tool: no allowance, no runway


def _h29(ctx: Ctx) -> None:
    ctx.synth(["hermes"], days=10, seed=4)
    d = ctx.json_report("--tool", "hermes", "--allowance", "20")[0]
    assert d["unit"] == "usd" and d["allowance"] == 20.0
    assert d["status"] != "UNLIMITED"
    assert d["runway_days"] is not None
    assert d["used"] > 0


HERMES_CASES = [
    uc(UseCase("UC-26", "Hermes + OpenRouter", "OpenRouter credits are the native unit",
               "Hermes state.db with OpenRouter-billed sessions",
               "HermesAdapter().events()",
               "OpenRouter rows carry native_unit USD and a positive native cost", _h26)),
    uc(UseCase("UC-27", "Hermes + local Ollama", "Local rows stay unpriced",
               "Same state.db, sessions served by a local Ollama endpoint",
               "HermesAdapter().events()",
               "local events have no USD estimate and no native cost, but real token counts", _h27)),
    uc(UseCase("UC-28", "Hermes user", "No allowance means no runway",
               "Usage-only tool with no provider-imposed budget",
               "token-finops report --tool hermes --compact",
               "the compact line reports an unlimited (inf) runway", _h28)),
    uc(UseCase("UC-29", "Hermes user", "Self-set $20/month budget",
               "The user decides $20 of OpenRouter credit is the monthly budget",
               "token-finops report --tool hermes --allowance 20",
               "allowance 20 USD, a finite runway and a real status instead of UNLIMITED", _h29)),
]


# =========================================================================== #
# Category 6: usage-only tools (OpenCode, Cline/Roo/Kilo, Aider, Continue.dev)
# =========================================================================== #
def _o30(ctx: Ctx) -> None:
    ctx.synth(["opencode"], days=8, seed=2)
    d = ctx.json_report("--tool", "opencode")[0]
    assert d["unit"] == "usd" and d["window"] == "30d"
    assert d["allowance"] is None and d["status"] == "UNLIMITED"
    assert d["used"] > 0


def _o31(ctx: Ctx) -> None:
    root = ctx.home / ".config" / "Code" / "User" / "globalStorage"
    build_synthetic_cline(str(root), tasks=6, seed=2)
    ctx.monkeypatch.setenv("TOKEN_FINOPS_CLINE_DIRS", str(root))
    events = ClineAdapter().events()
    assert {e.tags.get("extension") for e in events} == {"cline", "roo", "kilo"}
    assert any(e.is_local_model for e in events)
    assert all(e.usd_estimate > 0 for e in events if not e.is_local_model)


def _o32(ctx: Ctx) -> None:
    ctx.synth(["aider"], days=5)
    ctx.monkeypatch.setenv("TOKEN_FINOPS_AIDER_DIRS", str(ctx.home))
    ctx.monkeypatch.setenv("TOKEN_FINOPS_AIDER_ANALYTICS",
                           str(ctx.home / ".aider" / "analytics.jsonl"))
    d = ctx.json_report("--tool", "aider")[0]
    assert d["unit"] == "usd"
    assert d["used"] == pytest.approx(0.17, abs=0.05)   # $0.15 + $0.02 from the chat history
    assert d["status"] == "UNLIMITED"


def _o33(ctx: Ctx) -> None:
    ctx.synth(["continue"], days=5)
    out = ctx.run_cli("report", "--tool", "continue")
    assert "Continue" in out
    assert "calls:            2" in out
    assert "API-equivalent:" in out


OTHER_TOOL_CASES = [
    uc(UseCase("UC-30", "OpenCode user", "Usage-only report in USD",
               "opencode.db with anthropic/openai/ollama sessions",
               "token-finops report --tool opencode --json",
               "unit usd over a sliding 30d window, no allowance -> UNLIMITED with real spend", _o30)),
    uc(UseCase("UC-31", "Cline / Roo / Kilo user", "All three VS Code extensions found",
               "globalStorage trees for all three extension ids",
               "ClineAdapter().events()",
               "events tagged cline/roo/kilo; local tasks unpriced, cloud tasks priced", _o31)),
    uc(UseCase("UC-32", "Aider user", "Chat history is the telemetry",
               ".aider.chat.history.md plus .aider/analytics.jsonl in the home directory",
               "token-finops report --tool aider --json",
               "the per-message costs from the history add up (~$0.17)", _o32)),
    uc(UseCase("UC-33", "Continue.dev user", "Sessions folder parsed",
               ".continue/sessions/sessions.json plus one session file",
               "token-finops report --tool continue",
               "two calls summarised with an API-equivalent dollar figure", _o33)),
]


# =========================================================================== #
# Category 7: cross-tool roll-up (binding constraint, never summing units)
# =========================================================================== #
def _x34(ctx: Ctx) -> None:
    copilot = compute_runway([make_event(days_ago=d, now=NOW, aiu=45.0) for d in range(15)],
                             month_policy(1500.0), now=NOW)
    gemini = compute_runway(
        [make_event(days_ago=i / 1440.0, now=NOW, tool="gemini_cli", model="gemini-2.5-pro",
                    aiu=None, native_unit=None) for i in range(600)],
        GeminiCliAdapter().default_policy(), now=NOW)
    binding = binding_constraint([copilot, gemini])
    assert binding is gemini                      # the daily request quota bites first
    assert binding.tool == "gemini_cli" and binding.unit is Unit.REQUESTS
    assert binding.runway_days < copilot.runway_days


def _x35(ctx: Ctx) -> None:
    ctx.synth(["copilot", "gemini_cli"], days=6, seed=5)
    payload = ctx.json_report("--budget", "200000")
    units = {d["unit"] for d in payload}
    assert units == {"aiu", "requests"}           # heterogeneous units, side by side
    assert len(payload) == 2
    for d in payload:                             # no aggregate/total key anywhere
        assert "total" not in d
    text = ctx.run_cli("report", "--budget", "200000")
    assert text.count("binding constraint:") == 1


def _x36(ctx: Ctx) -> None:
    tools = ["copilot", "codex", "gemini_cli", "hermes"]
    ctx.synth(tools, days=6, seed=6)
    lines = [ln for ln in ctx.run_cli("report", "--compact").splitlines() if ln.strip()]
    tool_lines = [ln for ln in lines if not ln.startswith("binding constraint:")]
    assert len(tool_lines) == len(tools)
    assert all("runway" in ln for ln in tool_lines)
    assert lines[-1].startswith("binding constraint:")   # plus the one roll-up line


def _x37(ctx: Ctx) -> None:
    # Back from three weeks of holiday: nothing burned in the current cycle.
    _copilot_db(ctx, [{"ts": REAL_NOW - timedelta(days=40), "session": "old", "inp": 10, "out": 10,
                       "nano_aiu": int(100 * 1e9)}])
    raw = ctx.run_cli("report", "--json", "--budget", "1500")
    assert "Infinity" not in raw and "NaN" not in raw
    d = json.loads(raw)[0]
    assert d["runway_days"] is None               # infinite runway serialises as null
    assert d["used"] == 0.0 and d["status"] == "OK"


def _x38(ctx: Ctx) -> None:
    copilot = compute_runway([make_event(days_ago=d, now=NOW, aiu=45.0) for d in range(15)],
                             month_policy(1500.0), now=NOW)
    hermes = compute_runway([make_event(days_ago=1, now=NOW, tool="hermes", model="gpt-oss-120b",
                                        aiu=None, native_unit=None, usd=1.0)],
                            BudgetPolicy(tool="hermes", window_id="30d", unit=Unit.USD,
                                         cycle=CycleKind.SLIDING_FROM_FIRST_USE,
                                         window_length=timedelta(days=30), allowance=None),
                            now=NOW)
    assert hermes.status is Status.UNLIMITED
    assert binding_constraint([copilot, hermes]) is copilot
    assert binding_constraint([hermes]) is None   # nothing bounded -> nothing binds


CROSS_TOOL_CASES = [
    uc(UseCase("UC-34", "Multi-tool developer", "Which budget runs out first",
               "Copilot Pro comfortably on pace, Gemini free tier already at 60 % by noon",
               "binding_constraint([copilot_runway, gemini_runway])",
               "the Gemini requests/day runway is returned as the binding constraint", _x34)),
    uc(UseCase("UC-35", "Multi-tool developer", "Units are never summed",
               "Copilot (AI units) and Gemini (requests/day) side by side",
               "token-finops report --json",
               "two entries with units aiu and requests, no aggregate; one binding-constraint line",
               _x35)),
    uc(UseCase("UC-36", "Multi-tool developer", "One line per tool",
               "Copilot, Codex, Gemini and Hermes data all present",
               "token-finops report --compact",
               "one line per tool (four), each with a runway, plus the binding-constraint line", _x36)),
    uc(UseCase("UC-37", "Copilot Pro (1500 AIU)", "Back from holiday: JSON stays strict",
               "The only usage is 40 days old, so the current cycle is empty",
               "token-finops report --json --budget 1500",
               "valid JSON, no Infinity/NaN: an unbounded runway serialises as null", _x37)),
    uc(UseCase("UC-38", "Multi-tool developer", "Unlimited tools cannot bind",
               "Copilot with an allowance, Hermes with none",
               "binding_constraint([...])",
               "the UNLIMITED Hermes runway is ignored; Copilot binds; an all-unlimited list -> None",
               _x38)),
]


# =========================================================================== #
# Category 8: savings / break-even (local box vs cloud)
# =========================================================================== #
def _s39(ctx: Ctx) -> None:
    out = cmd_savings(_savings_args(utilization=0.2))
    assert "CLOUD CHEAPER" in out
    assert "at 20% utilisation" in out
    assert "break-even utilisation: 60%" in out


def _s40(ctx: Ctx) -> None:
    low = cmd_savings(_savings_args(utilization=0.2))
    high = cmd_savings(_savings_args(utilization=0.8))
    assert "LOCAL CHEAPER" in high
    low_total = float(low.split("local total:       $")[1].split(" ")[0])
    high_total = float(high.split("local total:       $")[1].split(" ")[0])
    assert high_total < low_total / 3            # capex per token falls with utilisation


def _s41(ctx: Ctx) -> None:
    out = cmd_savings(_savings_args(power="solar-de-feed-in", utilization=0.8))
    assert "opportunity cost = feed-in tariff" in out
    energy_line = next(ln for ln in out.splitlines() if "energy cost:" in ln)
    cost = float(energy_line.split("$")[1].split(" ")[0])
    assert cost > 0.0                            # your own solar is not free
    assert "LOCAL CHEAPER" in out


def _s42(ctx: Ctx) -> None:
    out = cmd_savings(_savings_args(hardware="rtx-4090-workstation", model="llama-3.3-70b",
                                    utilization=0.9))
    assert "no utilisation makes this box win" in out
    lc = LocalCost(hardware="x", model="y", tok_s=20.0, load_w=450.0, price_usd=3000.0,
                   lifetime_years=3.0, utilization=0.9, tariff="grid-de-household",
                   eur_per_kwh=0.37, eur_per_usd=0.92)
    assert lc.break_even_utilization(cloud_blended_usd_per_mtok("haiku")) is None


def _s43(ctx: Ctx) -> None:
    _sonnet_session(ctx, 30, out=200_000)         # 6M output tokens of Sonnet-class work
    out = cmd_break_even(_break_even_args())
    assert "LOCAL WOULD ALREADY BE CHEAPER" in out
    assert "sonnet" in out


def _s44(ctx: Ctx) -> None:
    _sonnet_session(ctx, 2, out=200)              # a couple of tiny calls
    out = cmd_break_even(_break_even_args())
    assert "cloud still cheaper" in out
    assert "never pays off within its lifetime" in out


SAVINGS_CASES = [
    uc(UseCase("UC-39", "Team lead evaluating hardware", "Mac Studio at 20 % utilisation",
               "$3,999 box, 3-year life, German household power, Qwen3-32B vs Sonnet-class cloud",
               "token-finops savings --utilization 0.2",
               "capex-dominated: CLOUD CHEAPER, break-even at 60 % utilisation", _s39)),
    uc(UseCase("UC-40", "Team lead evaluating hardware", "Same box at 80 % utilisation",
               "The same box, but actually inferring 19 h a day",
               "token-finops savings --utilization 0.8",
               "LOCAL CHEAPER; $/MTok drops by more than 3x versus 20 %", _s40)),
    uc(UseCase("UC-41", "Solar-powered developer", "Own solar is not free",
               "Same box on PV self-consumption, priced at the forgone feed-in tariff",
               "token-finops savings --power solar-de-feed-in --utilization 0.8",
               "energy cost > $0 (opportunity cost), still LOCAL CHEAPER", _s41)),
    uc(UseCase("UC-42", "Gamer with an RTX 4090", "Electricity alone beats the cloud price",
               "70B model on a 450 W workstation at German household rates",
               "token-finops savings --hardware rtx-4090-workstation --model llama-3.3-70b",
               "'no utilisation makes this box win'; break_even_utilization() is None", _s42)),
    uc(UseCase("UC-43", "Heavy Claude Code user", "The box would already have paid off",
               "6M Sonnet-class output tokens replayed against a $3,999 box",
               "token-finops break-even",
               "'LOCAL WOULD ALREADY BE CHEAPER' on the replaceable (haiku/sonnet) tiers", _s43)),
    uc(UseCase("UC-44", "Occasional Claude Code user", "The box never pays off",
               "Two small Sonnet calls replayed against the same box",
               "token-finops break-even",
               "'cloud still cheaper' and 'never pays off within its lifetime'", _s44)),
]


# =========================================================================== #
# Category 9: the synthetic generator (offline demos, bug reports, this suite)
# =========================================================================== #
SYNTH_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _copilot_runway(ctx: Ctx, scenario: str, allowance: float, *, days: int = 14, seed: int = 42):
    from token_finops_cli.adapters.copilot import CopilotAdapter
    out = ctx.tmp_path / f"synth-{scenario}"
    generate(str(out), tools=["copilot"], days=days, scenario=scenario, seed=seed, now=SYNTH_NOW)
    adapter = CopilotAdapter(str(out / ".copilot" / "session-store.db"))
    events = adapter.events()
    return events, compute_runway(events, adapter.default_policy(allowance), now=SYNTH_NOW)


def _y45(ctx: Ctx) -> None:
    _events, r = _copilot_runway(ctx, "steady", 300_000.0)
    assert r.status is Status.OK
    assert r.runway_days > r.days_left
    assert 0.0 < r.used_fraction < 0.75


def _y46(ctx: Ctx) -> None:
    _events, r = _copilot_runway(ctx, "exhausted", 50_000.0)
    assert r.status in (Status.CRITICAL, Status.EXHAUSTED)
    assert r.used_fraction > 1.0


def _y47(ctx: Ctx) -> None:
    _events, r = _copilot_runway(ctx, "burst", 300_000.0, days=25)
    assert r.burn_per_day_ema > r.burn_per_day_avg


def _y48(ctx: Ctx) -> None:
    events, _r = _copilot_runway(ctx, "weekend", 300_000.0)
    assert events
    assert not [e for e in events if e.ts_utc.weekday() >= 5]


def _y49(ctx: Ctx) -> None:
    events, r = _copilot_runway(ctx, "fresh", 300_000.0)
    assert events
    oldest = min(e.ts_utc for e in events)
    assert (SYNTH_NOW - oldest) <= timedelta(days=2, hours=1)
    assert r.status in (Status.OK, Status.WARN)


def _y50(ctx: Ctx) -> None:
    """`eval "$(token-finops synth --print-env)" && token-finops report` in a fresh process."""
    out = ctx.tmp_path / "demo-home"
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    base_env = {**os.environ, "PYTHONPATH": src}
    synth = subprocess.run([sys.executable, "-m", "token_finops_cli", "synth", "--out", str(out),
                            "--tools", "copilot,codex,hermes", "--days", "6", "--print-env"],
                           capture_output=True, text=True, check=True, env=base_env)
    env = dict(base_env)
    for line in synth.stdout.splitlines():
        if line.startswith("export "):
            var, _, val = line[len("export "):].partition("=")
            env[var] = val
    report = subprocess.run([sys.executable, "-m", "token_finops_cli", "report", "--compact"],
                            capture_output=True, text=True, check=True, env=env)
    assert "GitHub Copilot CLI" in report.stdout
    assert "OpenAI Codex CLI" in report.stdout or "Codex" in report.stdout
    assert "Hermes Agent" in report.stdout


SYNTH_CASES = [
    uc(UseCase("UC-45", "Demo / bug reporter", "Steady scenario stays healthy",
               "14 days of even usage against a generous 300k AI-unit enterprise pool",
               "token-finops synth --out DIR --scenario steady",
               "runway outlasts the reset -> OK, under 75 % of the pool used", _y45)),
    uc(UseCase("UC-46", "Demo / bug reporter", "Exhausted scenario blows the budget",
               "per-event cost scaled 25x against the default 50,000 AIU allowance",
               "token-finops synth --out DIR --scenario exhausted",
               "used > 100 % -> CRITICAL or EXHAUSTED", _y46)),
    uc(UseCase("UC-47", "Demo / bug reporter", "Burst scenario is visible in the EMA",
               "25 days that end in two 5x days, checked late in the month",
               "token-finops synth --out DIR --scenario burst",
               "EMA daily burn exceeds the cycle average", _y47)),
    uc(UseCase("UC-48", "Demo / bug reporter", "Weekend scenario has no weekend usage",
               "Two weeks of usage generated with weekends zeroed out",
               "token-finops synth --out DIR --scenario weekend",
               "no event falls on a Saturday or Sunday (UTC)", _y48)),
    uc(UseCase("UC-49", "Demo / bug reporter", "Fresh scenario: first use was yesterday",
               "Two weeks requested, but usage suppressed before day-offset 2",
               "token-finops synth --out DIR --scenario fresh",
               "all events within the last two days, status still OK/WARN", _y49)),
    uc(UseCase("UC-50", "Demo / bug reporter", "print-env round trip through report",
               "A generated fake home for Copilot, Codex and Hermes",
               'eval "$(token-finops synth --out DIR --print-env)" && token-finops report --compact',
               "a fresh process reports all three tools from the synthetic tree", _y50)),
]


# =========================================================================== #
# The tests: one parametrised function per category
# =========================================================================== #
@pytest.mark.parametrize("case", COPILOT_CASES, ids=_ids)
def test_copilot_plans(case: UseCase, ctx: Ctx) -> None:
    case.check(ctx)


@pytest.mark.parametrize("case", CLAUDE_CASES, ids=_ids)
def test_claude_code_subscribers(case: UseCase, ctx: Ctx) -> None:
    case.check(ctx)


@pytest.mark.parametrize("case", CODEX_CASES, ids=_ids)
def test_codex(case: UseCase, ctx: Ctx) -> None:
    case.check(ctx)


@pytest.mark.parametrize("case", GEMINI_CASES, ids=_ids)
def test_gemini_cli(case: UseCase, ctx: Ctx) -> None:
    case.check(ctx)


@pytest.mark.parametrize("case", HERMES_CASES, ids=_ids)
def test_hermes(case: UseCase, ctx: Ctx) -> None:
    case.check(ctx)


@pytest.mark.parametrize("case", OTHER_TOOL_CASES, ids=_ids)
def test_usage_only_tools(case: UseCase, ctx: Ctx) -> None:
    case.check(ctx)


@pytest.mark.parametrize("case", CROSS_TOOL_CASES, ids=_ids)
def test_cross_tool_rollup(case: UseCase, ctx: Ctx) -> None:
    case.check(ctx)


@pytest.mark.parametrize("case", SAVINGS_CASES, ids=_ids)
def test_savings_and_break_even(case: UseCase, ctx: Ctx) -> None:
    case.check(ctx)


@pytest.mark.parametrize("case", SYNTH_CASES, ids=_ids)
def test_synthetic_scenarios(case: UseCase, ctx: Ctx) -> None:
    case.check(ctx)


def test_table_is_complete_and_unique() -> None:
    """The table is the spec: 50 cases, unique ids, every one wired to a test."""
    assert len(ALL_CASES) == 50
    assert len({c.id for c in ALL_CASES}) == 50
    parametrised = (COPILOT_CASES + CLAUDE_CASES + CODEX_CASES + GEMINI_CASES + HERMES_CASES
                    + OTHER_TOOL_CASES + CROSS_TOOL_CASES + SAVINGS_CASES + SYNTH_CASES)
    assert [c.id for c in parametrised] == [c.id for c in ALL_CASES]
    for c in ALL_CASES:
        assert c.persona and c.title and c.setup and c.command and c.expected


# --------------------------------------------------------------------------- #
# docs/USECASES.md generator
# --------------------------------------------------------------------------- #
def _escape(text: str) -> str:
    return text.replace("|", "\\|")


def markdown() -> str:
    lines = [
        "# Use cases",
        "",
        "Generated from `token-finops-cli/tests/test_usecases.py` "
        "(`PYTHONPATH=src python3 tests/test_usecases.py --markdown`). "
        "Every row is an executed test: the ID is the pytest parameter id, so "
        "`pytest -k UC-13` runs exactly that case.",
        "",
        "| ID | Persona | Scenario | Command | Expected |",
        "|---|---|---|---|---|",
    ]
    for c in ALL_CASES:
        lines.append(
            f"| {c.id} | {_escape(c.persona)} | {_escape(c.title)}: {_escape(c.setup)} "
            f"| `{_escape(c.command)}` | {_escape(c.expected)} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    if "--markdown" in sys.argv:
        print(markdown())
    else:
        print(f"{len(ALL_CASES)} use cases; pass --markdown to emit docs/USECASES.md")
