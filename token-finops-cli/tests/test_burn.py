"""Unit tests for `token_finops_cli.burn` (plan catalogue, maxing multiplier, efficiency ratios,
prepaid rates, report assembly and rendering). No real telemetry, no network."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from token_finops_cli import burn
from token_finops_cli.core.pricing import estimate_usd

from conftest import NOW, make_event


# --------------------------------------------------------------------------- #
# plans
# --------------------------------------------------------------------------- #
def test_load_plans_merges_user_override_by_id(tmp_path):
    user = tmp_path / "plans.json"
    user.write_text(json.dumps({"plans": [
        {"id": "claude:pro", "usd_month": 25.0},                                   # partial override
        {"id": "acme:team", "tool": "claude_code", "name": "Acme", "usd_month": 42.0},  # new plan
        {"no_id": True}, "garbage",                                                  # ignored
    ]}))
    cat = burn.load_plans(user_path=str(user))
    by_id = {p["id"]: p for p in cat["plans"]}
    assert by_id["claude:pro"]["usd_month"] == 25.0
    assert by_id["claude:pro"]["name"] == "Claude Pro"  # untouched fields survive the merge
    assert by_id["acme:team"]["tool"] == "claude_code"
    assert len(cat["plans"]) == 15  # 14 bundled + 1 new, no duplicate for the override


@pytest.mark.parametrize("payload", ["not json {", json.dumps(["a", "list"]), json.dumps(42)])
def test_load_plans_ignores_corrupt_or_non_dict_override(tmp_path, payload):
    user = tmp_path / "plans.json"
    user.write_text(payload)
    bundled = burn.load_plans(user_path=str(tmp_path / "missing.json"))
    assert len(burn.load_plans(user_path=str(user))["plans"]) == len(bundled["plans"]) == 14


def test_plans_for_claude_code_returns_four_plans(tmp_path):
    cat = burn.load_plans(user_path=str(tmp_path / "missing.json"))
    plans = burn.plans_for("claude_code", cat)
    assert len(plans) == 4
    assert {p["id"] for p in plans} == {"claude:pro", "claude:max-5x", "claude:max-20x", "claude:team"}
    assert burn.plans_for("hermes", cat) == []


def test_plans_for_skips_plans_without_numeric_price():
    cat = {"plans": [{"id": "x:a", "tool": "x", "usd_month": "20"}, {"id": "x:b", "tool": "x", "usd_month": 20}]}
    assert [p["id"] for p in burn.plans_for("x", cat)] == ["x:b"]


@pytest.mark.parametrize("mult, label", [
    (0.49, "subsidising the provider"), (0.5, "break-even-ish"), (0.99, "break-even-ish"),
    (1, "normal heavy use"), (2.99, "normal heavy use"), (3, "token maxing"), (9.99, "token maxing"),
    (10, "arson"), (1e9, "arson"), (None, "unknown"),
])
def test_maxing_label_boundaries(mult, label):
    assert burn.maxing_label(mult) == label


def test_plan_equivalents_arithmetic_and_skips_free_plans():
    plans = [{"id": "p:a", "name": "A", "usd_month": 100.0},
             {"id": "p:free", "name": "Free", "usd_month": 0},
             {"id": "p:neg", "name": "Neg", "usd_month": -5}]
    rows = burn.plan_equivalents(usd=250.0, usd_per_30d=350.0, plans=plans)
    assert [r["id"] for r in rows] == ["p:a"]
    r = rows[0]
    assert r["plan_months"] == pytest.approx(2.5)
    assert r["maxing"] == pytest.approx(3.5)
    assert r["label"] == "token maxing"
    assert r["usd_month"] == 100.0


# --------------------------------------------------------------------------- #
# efficiency
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model, tier", [
    ("claude-fable-5-1", "frontier"), ("claude-sonnet-5", "mid"), ("claude-haiku-4-5", "cheap"),
    ("claude-fable-5-1-20260601", "frontier"),  # dated ids normalise to the same tier
    ("no-such-model-xyz", "unknown"),
])
def test_model_tier(home, model, tier):
    assert burn.model_tier(model) == tier


def _priced(days_ago, model, **kw):
    """A claude_code event whose usd_estimate is the real list-price estimate."""
    e = make_event(days_ago, tool="claude_code", model=model, aiu=None, **kw)
    e.usd_estimate = estimate_usd(model, e.input_tokens, e.output_tokens, e.cache_read_tokens, e.cache_write_tokens)
    return e


def test_efficiency_empty_list_gives_none_ratios():
    eff = burn.efficiency([])
    assert eff["calls"] == 0 and eff["usd"] == 0.0 and eff["total_tokens"] == 0
    for k in ("cache_hit", "output_share", "usd_per_1k_output", "tokens_per_call", "frontier_share",
              "cheap_share", "subagent_share", "most_expensive_model", "cheapest_model",
              "all_frontier_usd", "all_cheap_usd", "routing_dividend_usd"):
        assert eff[k] is None, k
    assert eff["models"] == {} and eff["subagents"] == 0


def test_efficiency_ratios_on_hand_built_events(home):
    # input side: 1000 fresh + 3000 cache read + 1000 cache write = 5000; output 500 -> total 5500
    evs = [make_event(0, tool="claude_code", model="claude-sonnet-5", usd=2.0, inp=1000, out=300, cr=3000, cw=1000),
           make_event(0, tool="claude_code", model="claude-sonnet-5", usd=1.0, inp=0, out=200, agent="sub-1")]
    eff = burn.efficiency(evs)
    assert eff["calls"] == 2 and eff["total_tokens"] == 5500 and eff["output_tokens"] == 500
    assert eff["usd"] == pytest.approx(3.0)
    assert eff["cache_hit"] == pytest.approx(3000 / 5000)
    assert eff["output_share"] == pytest.approx(500 / 5500)
    assert eff["usd_per_1k_output"] == pytest.approx(3.0 / 500 * 1000)
    assert eff["tokens_per_call"] == pytest.approx(2750)
    assert eff["subagent_share"] == pytest.approx(1.0 / 3.0)
    assert eff["subagents"] == 1
    assert eff["frontier_share"] == 0.0 and eff["cheap_share"] == 0.0  # sonnet is mid tier
    assert eff["models"] == {"claude-sonnet-5": pytest.approx(3.0)}
    # a single model in the mix -> no routing counterfactual
    assert eff["most_expensive_model"] == eff["cheapest_model"] == "claude-sonnet-5"
    assert eff["routing_dividend_usd"] is None and eff["all_frontier_usd"] is None


def test_efficiency_skips_events_without_usd(home):
    evs = [make_event(0, tool="claude_code", model="claude-sonnet-5", usd=2.0, inp=1000, out=100),
           make_event(0, tool="claude_code", model="claude-fable-5-1", usd=None, inp=1000, out=100, agent="a1")]
    eff = burn.efficiency(evs)
    assert eff["calls"] == 2  # still counted as a call...
    assert eff["usd"] == pytest.approx(2.0)  # ...but not in any dollar figure
    assert eff["frontier_share"] == 0.0
    assert "claude-fable-5-1" not in eff["models"]
    assert eff["routing_dividend_usd"] is None  # the unpriced fable call does not enter the model mix
    assert eff["subagent_share"] == 0.0


def test_efficiency_frontier_share_and_routing_dividend(home):
    evs = [_priced(0.1, "claude-fable-5-1", inp=10_000, out=2_000, cr=50_000, cw=5_000),
           _priced(0.2, "claude-haiku-4-5", inp=10_000, out=2_000, cr=50_000, cw=5_000, agent="h1"),
           _priced(0.3, "claude-haiku-4-5", inp=10_000, out=2_000, agent="h1")]
    eff = burn.efficiency(evs)
    fable_usd = evs[0].usd_estimate
    assert eff["frontier_share"] == pytest.approx(fable_usd / eff["usd"])
    assert eff["cheap_share"] == pytest.approx(1 - eff["frontier_share"])
    assert eff["most_expensive_model"] == "claude-fable-5-1" and eff["cheapest_model"] == "claude-haiku-4-5"
    assert eff["all_frontier_usd"] > eff["usd"] > eff["all_cheap_usd"]
    assert eff["routing_dividend_usd"] == pytest.approx(eff["all_frontier_usd"] - eff["usd"])
    assert eff["subagent_share"] == pytest.approx((evs[1].usd_estimate + evs[2].usd_estimate) / eff["usd"])
    # cache: 100k of 140k input-side tokens came from cache; that is cheaper than billing them fresh
    assert eff["cache_hit"] == pytest.approx(100_000 / 140_000)
    assert eff["no_cache_usd"] > eff["usd"] and eff["cache_saved_usd"] == pytest.approx(eff["no_cache_usd"] - eff["usd"])


def test_span_and_active_days():
    assert burn.span_days([]) == 0.0
    one = [make_event(0)]
    assert burn.span_days(one) == 1.0  # floor of one day
    assert burn.active_days(one) == 1
    # NOW is 12:00 UTC on the 15th; 2.2 and 2.4 days earlier both fall on the 13th
    evs = [make_event(0), make_event(2.2), make_event(2.4)]
    assert burn.span_days(evs) == pytest.approx(2.4)
    assert burn.active_days(evs) == 2


# --------------------------------------------------------------------------- #
# prepaid
# --------------------------------------------------------------------------- #
def test_parse_rate_two_part_defaults_cache_rates():
    assert burn.parse_rate("3/15") == {"input": 3.0, "output": 15.0, "cache_read": pytest.approx(0.3),
                                      "cache_write": pytest.approx(3.75)}


def test_parse_rate_four_part_and_three_part():
    assert burn.parse_rate("3/15/0.5/4") == {"input": 3.0, "output": 15.0, "cache_read": 0.5, "cache_write": 4.0}
    assert burn.parse_rate("2/10/0.1") == {"input": 2.0, "output": 10.0, "cache_read": 0.1,
                                          "cache_write": pytest.approx(2.5)}


@pytest.mark.parametrize("bad", ["3", "", "a/b"])
def test_parse_rate_rejects_bad_specs(bad):
    with pytest.raises(ValueError):
        burn.parse_rate(bad)


def test_prepaid_usd_arithmetic_on_one_event():
    e = make_event(0, inp=1_000_000, out=100_000, cr=2_000_000, cw=400_000)
    rate = burn.parse_rate("3/15")
    # 1M*3 + 0.1M*15 + 2M*0.3 + 0.4M*3.75 = 3 + 1.5 + 0.6 + 1.5
    assert burn.prepaid_usd([e], rate) == pytest.approx(6.6)
    assert burn.prepaid_usd([], rate) == 0.0


# --------------------------------------------------------------------------- #
# burn_report + render_burn
# --------------------------------------------------------------------------- #
PLANS = [{"id": "claude:pro", "name": "Claude Pro", "usd_month": 20.0},
         {"id": "claude:max-20x", "name": "Claude Max 20x", "usd_month": 200.0}]


def _events():
    # 10 days of one $30 call each -> $300 over a 9-day span -> $1000 per 30 days
    return [make_event(d, tool="claude_code", model="claude-sonnet-5", usd=30.0, inp=1000, out=100)
            for d in range(10)]


def test_burn_report_numbers_and_my_plan():
    r = burn.burn_report("claude_code", "Claude Code", _events(), PLANS, my_plan="claude:max-20x", label="test")
    assert r["usd"] == pytest.approx(300.0)
    assert r["span_days"] == pytest.approx(9.0) and r["active_days"] == 10
    assert r["usd_per_30d"] == pytest.approx(1000.0)
    assert r["my_plan"]["id"] == "claude:max-20x" and r["my_plan"]["maxing"] == pytest.approx(5.0)
    assert r["my_plan"]["label"] == "token maxing"
    assert r["first"] == NOW - timedelta(days=9) and r["last"] == NOW
    assert r["prepaid"] is None and r["discount"] is None and r["periods"] is None
    assert r["with_history"] is False


def test_render_marks_my_plan_and_hides_optional_blocks():
    r = burn.burn_report("claude_code", "Claude Code", _events(), PLANS, my_plan="claude:max-20x", label="test")
    text = "\n".join(burn.render_burn(r, "2026-09-04"))
    assert "Burn report: Claude Code (test)" in text
    yours = [ln for ln in text.splitlines() if ln.endswith("<- yours")]
    assert len(yours) == 1 and "Claude Max 20x" in yours[0]
    assert "on Claude Max 20x you burn 5.0x the fee" in text
    assert "discount" not in text and "prepaid" not in text
    assert "Burn efficiency" not in text and "By " not in text
    assert "reviewed 2026-09-04" in text


def test_render_without_my_plan_has_no_marker():
    r = burn.burn_report("claude_code", "Claude Code", _events(), PLANS)
    text = "\n".join(burn.render_burn(r, "2026-09-04"))
    assert "<- yours" not in text and "you burn" not in text
    assert r["my_plan"] is None


def test_render_no_plans_line():
    r = burn.burn_report("hermes", "Hermes Agent", _events(), [])
    text = "\n".join(burn.render_burn(r, "2026-09-04"))
    assert "no subscription plans known for this tool" in text
    assert r["plans"] == []


def test_render_discount_rate_and_efficiency_blocks():
    rate = burn.parse_rate("3/15")
    r = burn.burn_report("claude_code", "Claude Code", _events(), PLANS, rate=rate, discount=0.5)
    assert r["discount"] == {"factor": 0.5, "usd": pytest.approx(150.0)}
    assert r["prepaid"]["usd"] == pytest.approx(burn.prepaid_usd(_events(), rate))
    lines = burn.render_burn(r, "2026-09-04", show_efficiency=True)
    text = "\n".join(lines)
    assert "with 50% discount:" in text and "(list x 0.50)" in text
    assert "prepaid rate:" in text and "$3/15 in/out" in text and "$0.3/3.75 cache r/w" in text
    assert "Burn efficiency:" in text and "cache hit ratio" in text and "$ per 1k output" in text
    assert "Burn efficiency:" not in "\n".join(burn.render_burn(r, "2026-09-04", show_efficiency=False))


def test_render_empty_window():
    r = burn.burn_report("claude_code", "Claude Code", [], PLANS, my_plan="claude:pro")
    lines = burn.render_burn(r, "2026-09-04")
    assert lines[0].startswith("Burn report: Claude Code")
    assert any("no" in ln and "usage events in this window" in ln for ln in lines)
    assert r["first"] is None and r["usd_per_30d"] == 0.0


def test_burn_report_by_week_periods():
    r = burn.burn_report("claude_code", "Claude Code", _events(), PLANS, my_plan="claude:max-20x", by="week")
    assert r["by"] == "week" and r["periods"]
    keys = [g["period"] for g in r["periods"]]
    # NOW = 2026-09-15 (Tuesday, ISO week 38); 10 days back reaches 2026-09-06 (Sunday, week 36)
    assert keys == ["2026-W36", "2026-W37", "2026-W38"]
    assert keys == sorted(keys)
    for g in r["periods"]:
        assert g["usd_per_30d"] == pytest.approx(g["usd"] * 30 / 7)
        assert g["maxing"] == pytest.approx(g["usd_per_30d"] / 200.0)
        assert g["tokens"] == g["calls"] * 1100
    assert sum(g["days"] for g in r["periods"]) == 10
    assert sum(g["usd"] for g in r["periods"]) == pytest.approx(300.0)
    text = "\n".join(burn.render_burn(r, "2026-09-04"))
    assert "By ISO week:" in text and "2026-W37" in text and "maxing" in text
    assert "recorded history" not in text


def test_burn_report_by_month_without_plan_has_no_maxing():
    r = burn.burn_report("claude_code", "Claude Code", _events(), PLANS, by="month")
    assert [g["period"] for g in r["periods"]] == ["2026-09"]
    g = r["periods"][0]
    assert g["maxing"] is None
    assert g["usd_per_30d"] == pytest.approx(300.0 * 30 / 30)
    head = next(ln for ln in burn.render_burn(r, "x") if ln.strip().startswith("period"))
    assert "maxing" not in head


def test_burn_report_merges_history_rows():
    old = {"schema_version": 1, "tool": "claude_code", "day": "2026-07-04", "calls": 3, "input": 10, "output": 20,
           "cache_read": 30, "cache_write": 40, "usd": 7.0, "by_model": {"claude-sonnet-5": 7.0}}
    other = dict(old, tool="codex", day="2026-07-05")
    r = burn.burn_report("claude_code", "Claude Code", _events(), PLANS, by="month", history_rows=[old, other])
    assert r["with_history"] is True
    months = {g["period"]: g for g in r["periods"]}
    assert set(months) == {"2026-07", "2026-09"}
    assert months["2026-07"]["usd"] == pytest.approx(7.0) and months["2026-07"]["tokens"] == 100
    assert months["2026-07"]["usd_per_30d"] == pytest.approx(7.0 * 30 / 31)
    assert "(live telemetry + recorded history)" in "\n".join(burn.render_burn(r, "x"))
