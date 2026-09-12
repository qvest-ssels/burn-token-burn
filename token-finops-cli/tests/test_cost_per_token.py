"""Unit tests for `token_finops_cli.cost_per_token` (per-model $/1M-token aggregation,
the realized-vs-derived distinction, and the `cost-per-token` CLI). No real telemetry,
no network."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from token_finops_cli import cost_per_token as cpt
from token_finops_cli.core.model import Unit

from conftest import make_event, write_copilot_db


# --------------------------------------------------------------------------- #
# per_model_rows
# --------------------------------------------------------------------------- #
def test_pay_per_token_tool_gets_realized_not_derived():
    """Claude Code carries usd_estimate (a real list-price estimate); no native
    AIU/USD cost is set, so 'derived' must stay empty and 'realized' must be populated."""
    evs = [make_event(tool="claude_code", model="claude-sonnet-5", inp=1_000_000, out=0,
                      usd=2.0, aiu=None, native_unit=None) for _ in range(3)]
    rows = cpt.per_model_rows(evs, "claude_code")
    assert len(rows) == 1
    r = rows[0]
    assert r["calls"] == 3
    assert r["tokens"] == 3_000_000
    assert r["realized_usd_per_mtok"] == 2.0  # (3 * $2.0) / 3M tokens * 1e6
    assert r["derived_usd_per_mtok"] is None
    assert r["list_price_in"] == 2.0 and r["list_price_out"] == 10.0  # from core/pricing.py


def test_copilot_has_no_official_rate_only_derived():
    """Copilot never sets usd_estimate (adapters/copilot.py) -- only native_cost in AI
    credits. 1 credit = $0.01, so cost-per-token must fall back to the derived ratio."""
    evs = [make_event(tool="copilot", model="gpt-5", inp=500_000, out=500_000,
                      aiu=100.0, native_unit=Unit.AIU, usd=None)]
    rows = cpt.per_model_rows(evs, "copilot")
    r = rows[0]
    assert r["realized_usd_per_mtok"] is None
    # 100 AIU * $0.01/credit = $1.00, over 1,000,000 tokens -> $1.00/Mtok
    assert r["derived_usd_per_mtok"] == 1.0
    assert r["list_price_in"] == 1.25  # gpt-5 is still in the list-price table for comparison


def test_local_model_has_neither_realized_nor_derived():
    evs = [make_event(tool="cline", model="ollama/qwen3-32b", inp=1000, out=1000,
                      usd=None, aiu=None, native_unit=None)]
    rows = cpt.per_model_rows(evs, "cline")
    r = rows[0]
    assert r["realized_usd_per_mtok"] is None
    assert r["derived_usd_per_mtok"] is None
    assert r["list_price_in"] is None


def test_groups_by_normalized_model_id_and_sums_tokens():
    evs = [
        make_event(tool="claude_code", model="claude-sonnet-4-5-20250929", inp=100, out=50, usd=0.01,
                  aiu=None, native_unit=None),
        make_event(tool="claude_code", model="claude-sonnet-4-5", inp=200, out=100, usd=0.02,
                  aiu=None, native_unit=None),
    ]
    rows = cpt.per_model_rows(evs, "claude_code")
    assert len(rows) == 1
    assert rows[0]["model"] == "claude-sonnet-4-5"
    assert rows[0]["calls"] == 2
    assert rows[0]["tokens"] == 450


def test_rows_sorted_by_tokens_descending():
    evs = [
        make_event(tool="claude_code", model="claude-haiku-4-5", inp=10, out=0, usd=0.0001,
                  aiu=None, native_unit=None),
        make_event(tool="claude_code", model="claude-sonnet-5", inp=10_000, out=0, usd=0.02,
                  aiu=None, native_unit=None),
    ]
    rows = cpt.per_model_rows(evs, "claude_code")
    assert [r["model"] for r in rows] == ["claude-sonnet-5", "claude-haiku-4-5"]


# --------------------------------------------------------------------------- #
# render_cost_per_token
# --------------------------------------------------------------------------- #
def test_render_marks_derived_rows_with_legend():
    evs = [make_event(tool="copilot", model="gpt-5", inp=500_000, out=500_000, aiu=100.0,
                      native_unit=Unit.AIU, usd=None)]
    rows = cpt.per_model_rows(evs, "copilot")
    out = cpt.render_cost_per_token("GitHub Copilot CLI", "copilot", rows, "last 30d")
    text = "\n".join(out)
    assert "$1.00*" in text
    assert "not an official per-token price" in text
    assert "AI-credit billing" in text


def test_render_empty_rows():
    out = cpt.render_cost_per_token("GitHub Copilot CLI", "copilot", [], "last 30d")
    assert "no usage events in this window" in "\n".join(out)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_cost_per_token_no_data(home, run_cli):
    out = run_cli("cost-per-token")
    assert "No usage events found" in out


def test_cli_cost_per_token_reports_copilot_and_claude_code(home, run_cli):
    (home / ".copilot").mkdir()
    write_copilot_db(str(home / ".copilot" / "session-store.db"), [
        {"ts": datetime.now(timezone.utc), "session": "s1",
         "inp": 1000, "out": 500, "nano_aiu": 100_000_000, "model": "gpt-5"},
    ])
    out = run_cli("cost-per-token", "--tool", "copilot", "--since", "all")
    assert "GitHub Copilot CLI" in out
    assert "gpt-5" in out
    assert "derived" in out


def test_cli_cost_per_token_json(home, run_cli):
    (home / ".copilot").mkdir()
    write_copilot_db(str(home / ".copilot" / "session-store.db"), [
        {"ts": datetime.now(timezone.utc), "session": "s1",
         "inp": 1000, "out": 500, "nano_aiu": 100_000_000, "model": "gpt-5"},
    ])
    out = run_cli("cost-per-token", "--tool", "copilot", "--since", "all", "--json")
    data = json.loads(out)
    assert data[0]["tool"] == "copilot"
    assert data[0]["rows"][0]["derived_usd_per_mtok"] is not None
