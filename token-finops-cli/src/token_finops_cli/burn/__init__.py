"""`token-finops burn` — the fun part: how hard are you maxing your plan, and how
efficiently are you burning?

Subscriptions (Claude Pro/Max, Copilot Pro+, ChatGPT Pro, Google AI Ultra) never
publish a token allowance, so a flat fee cannot be turned into "$ per token".
What *can* be compared is the other way round: price the calls at pay-per-token
list prices (the API-equivalent the rest of this tool already computes) and
divide by the plan price. That ratio is the **maxing multiplier** — how many
times over you would have paid your subscription fee on the API.

    maxing = API_equivalent_usd_per_30d / plan_usd_per_month

  < 0.5   you are subsidising the provider
  0.5–1   break-even-ish; pay-per-token would be about the same
  1–3     normal heavy use — the plan pays off
  3–10    token maxing
  ≥ 10    arson

The second half is **burn efficiency**: of the tokens you push through, how
many came from cache, how much of the bill went to frontier-tier models, how
much to sub-agents, and what one thousand tokens of *actual answer* cost you.
Everything is a ratio of things we can observe locally — no provider secrets.
Plan prices live in `plans.json` (override: ~/.token-finops/plans.json).
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import timezone
from typing import Iterable, Optional

from ..core.model import UsageEvent
from ..core.pricing import estimate_usd, lookup
from ..report import fmt_tokens, fmt_usd, summarize
from . import history as hist

PLANS_FILE = os.path.join(os.path.dirname(__file__), "plans.json")
USER_PLANS_FILE = os.path.expanduser("~/.token-finops/plans.json")

MAXING_SCALE = [
    (0.5, "subsidising the provider"),
    (1.0, "break-even-ish"),
    (3.0, "normal heavy use"),
    (10.0, "token maxing"),
    (float("inf"), "arson"),
]

# model tiers by list output price ($/Mtok); "frontier" is the expensive end of the mix
TIER_BOUNDS = [(20.0, "frontier"), (6.0, "mid"), (0.0, "cheap")]


# --------------------------------------------------------------------------- #
# plans
# --------------------------------------------------------------------------- #
def load_plans(path: str = PLANS_FILE, user_path: str = USER_PLANS_FILE) -> dict:
    """Bundled catalogue merged with the user's override file (by plan id)."""
    with open(path, encoding="utf-8") as fh:
        cat = json.load(fh)
    plans = {p["id"]: p for p in cat.get("plans", []) if isinstance(p, dict) and "id" in p}
    try:
        with open(user_path, encoding="utf-8") as fh:
            user = json.load(fh)
        if isinstance(user, dict):
            for p in user.get("plans", []):
                if isinstance(p, dict) and "id" in p:
                    plans[p["id"]] = {**plans.get(p["id"], {}), **p}
    except (OSError, ValueError):
        pass
    cat["plans"] = list(plans.values())
    return cat


def plans_for(tool: str, catalogue: Optional[dict] = None) -> list[dict]:
    cat = catalogue or load_plans()
    return [p for p in cat["plans"] if p.get("tool") == tool and isinstance(p.get("usd_month"), (int, float))]


def maxing_label(multiplier: Optional[float]) -> str:
    if multiplier is None:
        return "unknown"
    for bound, label in MAXING_SCALE:
        if multiplier < bound:
            return label
    return MAXING_SCALE[-1][1]


def plan_equivalents(usd: float, usd_per_30d: float, plans: Iterable[dict]) -> list[dict]:
    rows = []
    for p in plans:
        price = float(p["usd_month"])
        if price <= 0:
            continue
        mult = usd_per_30d / price
        rows.append({"id": p["id"], "name": p["name"], "usd_month": price,
                     "plan_months": usd / price, "maxing": mult, "label": maxing_label(mult)})
    return rows


# --------------------------------------------------------------------------- #
# efficiency
# --------------------------------------------------------------------------- #
def model_tier(model: str) -> str:
    p = lookup(model)
    if p is None:
        return "unknown"
    out = float(p.get("output", 0.0))
    for bound, tier in TIER_BOUNDS:
        if out >= bound:
            return tier
    return "cheap"


def _reprice(e: UsageEvent, model: str) -> Optional[float]:
    return estimate_usd(model, e.input_tokens, e.output_tokens, e.cache_read_tokens, e.cache_write_tokens)


def _no_cache_price(e: UsageEvent) -> Optional[float]:
    """What the call would cost if every cached token were billed as fresh input."""
    return estimate_usd(e.model_norm, e.input_tokens + e.cache_read_tokens + e.cache_write_tokens, e.output_tokens)


def span_days(events: list[UsageEvent]) -> float:
    if not events:
        return 0.0
    ts = [e.ts_utc for e in events]
    return max(1.0, (max(ts) - min(ts)).total_seconds() / 86400.0)


def active_days(events: list[UsageEvent]) -> int:
    return len({e.ts_utc.astimezone(timezone.utc).date() for e in events})


def efficiency(events: list[UsageEvent]) -> dict:
    """Ratios of locally observable quantities. All shares are fractions 0..1 (or None)."""
    s = summarize(events)
    input_side = s["input"] + s["cache_read"] + s["cache_write"]
    total = input_side + s["output"]
    usd = s["usd"]

    by_tier = defaultdict(float)
    by_model = defaultdict(float)
    no_cache = 0.0
    most_expensive = None  # (output price, model) in the mix
    cheapest = None
    for e in events:
        if e.usd_estimate is None:
            continue
        by_tier[model_tier(e.model_norm)] += e.usd_estimate
        by_model[e.model_norm] += e.usd_estimate
        nc = _no_cache_price(e)
        no_cache += nc if nc is not None else e.usd_estimate
        p = lookup(e.model_norm)
        if p is not None:
            key = (float(p.get("output", 0.0)), e.model_norm)
            most_expensive = key if most_expensive is None or key > most_expensive else most_expensive
            cheapest = key if cheapest is None or key < cheapest else cheapest

    all_frontier = all_cheap = None
    if most_expensive and cheapest and most_expensive[1] != cheapest[1]:
        all_frontier = sum((_reprice(e, most_expensive[1]) or 0.0) for e in events if e.usd_estimate is not None)
        all_cheap = sum((_reprice(e, cheapest[1]) or 0.0) for e in events if e.usd_estimate is not None)

    subs = [e for e in events if e.agent_id]
    sub_usd = summarize(subs)["usd"] if subs else 0.0

    def share(x, denom):
        return None if not denom else x / denom

    return {
        "calls": s["calls"],
        "total_tokens": total,
        "output_tokens": s["output"],
        "usd": usd,
        "cache_hit": share(s["cache_read"], input_side),
        "cache_saved_usd": max(0.0, no_cache - usd),
        "no_cache_usd": no_cache,
        "output_share": share(s["output"], total),
        "usd_per_1k_output": share(usd, s["output"]) * 1000 if s["output"] and usd else None,
        "tokens_per_call": share(total, s["calls"]),
        "frontier_share": share(by_tier.get("frontier", 0.0), usd),
        "cheap_share": share(by_tier.get("cheap", 0.0), usd),
        "subagent_share": share(sub_usd, usd),
        "subagents": len(s["agents"]),
        "models": dict(sorted(by_model.items(), key=lambda kv: -kv[1])),
        "most_expensive_model": most_expensive[1] if most_expensive else None,
        "cheapest_model": cheapest[1] if cheapest else None,
        "all_frontier_usd": all_frontier,
        "all_cheap_usd": all_cheap,
        "routing_dividend_usd": (all_frontier - usd) if all_frontier is not None else None,
    }




# --------------------------------------------------------------------------- #
# prepaid / negotiated rates
# --------------------------------------------------------------------------- #
def parse_rate(spec: str) -> dict:
    """`IN/OUT[/CACHE_READ[/CACHE_WRITE]]` in $ per million tokens, e.g. `3/15` or `3/15/0.3/3.75`.
    Missing cache rates default to the Anthropic-style 10 % read / 125 % write of the input rate."""
    parts = [float(x) for x in spec.split("/")]
    if len(parts) < 2:
        raise ValueError("rate needs at least IN/OUT, e.g. --rate 3/15")
    inp, out = parts[0], parts[1]
    cr = parts[2] if len(parts) > 2 else inp * 0.10
    cw = parts[3] if len(parts) > 3 else inp * 1.25
    return {"input": inp, "output": out, "cache_read": cr, "cache_write": cw}


def prepaid_usd(events: Iterable[UsageEvent], rate: dict) -> float:
    """Every call at one flat negotiated rate — what a prepaid/committed-spend contract would bill."""
    total = 0.0
    for e in events:
        total += (e.input_tokens * rate["input"] + e.output_tokens * rate["output"]
                  + e.cache_read_tokens * rate["cache_read"] + e.cache_write_tokens * rate["cache_write"]) / 1e6
    return total


# --------------------------------------------------------------------------- #
# report assembly
# --------------------------------------------------------------------------- #
def burn_report(tool: str, display_name: str, events: list[UsageEvent], plans: list[dict],
                my_plan: Optional[str] = None, label: str = "", rate: Optional[dict] = None,
                discount: Optional[float] = None, by: Optional[str] = None,
                history_rows: Optional[list[dict]] = None) -> dict:
    evs = sorted(events, key=lambda e: e.ts_utc)
    eff = efficiency(evs)
    days = span_days(evs)
    per_30d = eff["usd"] * 30.0 / days if days else 0.0
    rows = plan_equivalents(eff["usd"], per_30d, plans)
    mine = next((r for r in rows if r["id"] == my_plan), None)
    price = next((float(p["usd_month"]) for p in plans if p["id"] == my_plan), None)

    periods = None
    if by:
        daily = hist.daily_aggregates(evs, tool)
        if history_rows:
            daily = hist.merge_live(daily, history_rows, tool)
        periods = []
        for key, g in hist.group(daily, by).items():
            g = dict(g)
            g["usd_per_30d"] = g["usd"] * 30.0 / g["period_days"]
            g["maxing"] = (g["usd_per_30d"] / price) if price else None
            periods.append(g)

    return {
        "tool": tool, "display_name": display_name, "label": label,
        "span_days": days, "active_days": active_days(evs),
        "first": evs[0].ts_utc if evs else None, "last": evs[-1].ts_utc if evs else None,
        "usd": eff["usd"], "usd_per_30d": per_30d,
        "plans": rows, "my_plan": mine, "efficiency": eff,
        "prepaid": None if rate is None else {"rate": rate, "usd": prepaid_usd(evs, rate)},
        "discount": None if discount is None else {"factor": discount, "usd": eff["usd"] * (1.0 - discount)},
        "periods": periods, "by": by, "with_history": bool(history_rows),
    }


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _render_periods(r: dict) -> list[str]:
    unit = {"day": "day", "week": "ISO week", "month": "month"}[r["by"]]
    out = [f"By {unit}" + (" (live telemetry + recorded history)" if r.get("with_history") else "") + ":"]
    head = f"  {'period':<10} {'days':>4} {'calls':>6} {'tokens':>8} {'API-eq $':>10} {'/30d $':>9}"
    head += f" {'maxing':>7}" if r["my_plan"] else ""
    out.append(head)
    any_partial = False
    for g in r["periods"]:
        label = g["period"] + ("*" if g.get("partial") else "")
        any_partial = any_partial or g.get("partial", False)
        line = (f"  {label:<10} {g['days']:>4} {g['calls']:>6} {fmt_tokens(g['tokens']):>8} "
                f"{g['usd']:>10.2f} {g['usd_per_30d']:>9.2f}")
        if r["my_plan"] and g["maxing"] is not None:
            line += f" {g['maxing']:>6.1f}x"
        out.append(line)
    if any_partial:
        out.append("  * partial period (fewer days observed than the calendar period)")
    return out


def render_burn(r: dict, pricing_date: str, show_efficiency: bool = False) -> list[str]:
    e = r["efficiency"]
    out = [f"Burn report: {r['display_name']}" + (f" ({r['label']})" if r["label"] else "")]
    if not e["calls"]:
        out.append("  no live usage events in this window")
        if r["periods"]:  # history-only window (--history reaching past the tool's own retention)
            out += [""] + _render_periods(r)
        return out
    out.append(f"  span: {r['first']:%Y-%m-%d} -> {r['last']:%Y-%m-%d}  ({r['span_days']:.1f} days, "
               f"{r['active_days']} active)   calls {e['calls']}   tokens {fmt_tokens(e['total_tokens'])}")
    out.append(f"  API-equivalent:  {fmt_usd(e['usd']):>10}   (list prices, reviewed {pricing_date})")
    out.append(f"  run-rate:        {fmt_usd(r['usd_per_30d']):>10}   per 30 days")
    if r["discount"]:
        d = r["discount"]
        out.append(f"  with {d['factor'] * 100:.0f}% discount: {fmt_usd(d['usd']):>8}   (list x {1 - d['factor']:.2f})")
    if r["prepaid"]:
        p, rt = r["prepaid"], r["prepaid"]["rate"]
        out.append(f"  prepaid rate:    {fmt_usd(p['usd']):>10}   at ${rt['input']:g}/{rt['output']:g} in/out, "
                   f"${rt['cache_read']:g}/{rt['cache_write']:g} cache r/w per Mtok "
                   f"({p['usd'] / e['usd'] * 100:.0f}% of list)" if e["usd"] else
                   f"  prepaid rate:    {fmt_usd(p['usd']):>10}")
    out.append("")
    if r["plans"]:
        out.append("Plan equivalents — maxing = API-equivalent per 30 days / plan price:")
        out.append(f"  {'plan':<28} {'$/month':>8} {'plan-months':>12} {'maxing':>8}  verdict")
        for p in r["plans"]:
            mark = "  <- yours" if r["my_plan"] and p["id"] == r["my_plan"]["id"] else ""
            out.append(f"  {p['name']:<28} {p['usd_month']:>8.2f} {p['plan_months']:>12.1f} "
                       f"{p['maxing']:>7.1f}x  {p['label']}{mark}")
        if r["my_plan"]:
            m = r["my_plan"]
            out.append(f"  -> on {m['name']} you burn {m['maxing']:.1f}x the fee in API terms: {m['label']}")
    else:
        out.append("Plan equivalents: no subscription plans known for this tool (pay-per-token or BYO key).")

    if r["periods"] is not None:
        out += [""] + _render_periods(r)

    if show_efficiency:
        out.append("")
        out.append("Burn efficiency:")
        out.append(f"  cache hit ratio      {_pct(e['cache_hit']):>7}   of input-side tokens served from cache")
        out.append(f"  cache saved          {fmt_usd(e['cache_saved_usd']):>9}   vs. {fmt_usd(e['no_cache_usd'])} "
                   "if nothing were cached")
        out.append(f"  output share         {_pct(e['output_share']):>7}   of all tokens are generated answer")
        out.append(f"  $ per 1k output      {fmt_usd(e['usd_per_1k_output']):>9}   what a thousand tokens of "
                   "actual answer cost")
        out.append(f"  tokens per call      {fmt_tokens(e['tokens_per_call'] or 0):>7}   context dragged along "
                   "per request")
        out.append(f"  frontier share       {_pct(e['frontier_share']):>7}   of $ on frontier-tier models"
                   + (f" ({e['most_expensive_model']})" if e["frontier_share"] else ""))
        out.append(f"  sub-agent share      {_pct(e['subagent_share']):>7}   of $ spent by {e['subagents']} sub-agents")
        if e["routing_dividend_usd"] is not None:
            out.append(f"  routing dividend     {fmt_usd(e['routing_dividend_usd']):>9}   saved vs. everything on "
                       f"{e['most_expensive_model']} ({fmt_usd(e['all_frontier_usd'])}); everything on "
                       f"{e['cheapest_model']} would be {fmt_usd(e['all_cheap_usd'])}")
    return out


# --------------------------------------------------------------------------- #
# CLI glue
# --------------------------------------------------------------------------- #
def add_burn_parser(sub):
    b = sub.add_parser("burn", help="plan equivalents (maxing multiplier), weekly/monthly tables, burn efficiency")
    b.add_argument("--tool", action="append", default=None, help="restrict to tool(s)")
    b.add_argument("--since", choices=["1d", "7d", "30d", "90d", "365d", "all"], default="30d")
    b.add_argument("--session", default=None, help="Claude Code: restrict to one session id prefix")
    b.add_argument("--plan", default=None, help="your plan id, e.g. claude:max-20x (see --plans)")
    b.add_argument("--plans", action="store_true", help="list the plan catalogue and exit")
    b.add_argument("--by", choices=["day", "week", "month"], default=None,
                   help="add a per-period table (weekly/monthly token report)")
    b.add_argument("--history", action="store_true",
                   help="merge ~/.token-finops/history.jsonl so --by reaches past the tools' own retention "
                        "(still bounded by --since; combine with --since all or 365d)")
    b.add_argument("--record", action="store_true",
                   help="fold today's live view into the history file (run from your refresh timer)")
    b.add_argument("--efficiency", "--nerdy", action="store_true", dest="efficiency",
                   help="show the burn-efficiency block (cache hit, $ per 1k output, frontier/sub-agent share, ...)")
    b.add_argument("--rate", default=None, metavar="IN/OUT[/CR[/CW]]",
                   help="also price everything at a flat prepaid rate in $/Mtok, e.g. 3/15 or 3/15/0.3/3.75")
    b.add_argument("--discount", type=float, default=None, metavar="FRACTION",
                   help="also show list price minus this fraction (0.5 = your 50%% promo)")
    b.add_argument("--history-file", default=None, help="override ~/.token-finops/history.jsonl")
    b.add_argument("--json", action="store_true")


_SINCE_DAYS = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365, "all": None}


def cmd_burn(args) -> str:
    from datetime import datetime, timedelta

    from ..cli import _adapters, _pricing_date

    cat = load_plans()
    if args.plans:
        lines = [f"Plan catalogue (reviewed {cat.get('review_date', '?')}; override ~/.token-finops/plans.json):"]
        for p in cat["plans"]:
            lines.append(f"  {p['id']:<20} {p['name']:<28} ${p['usd_month']:>7.2f}/mo   {p.get('notes', '')}")
        return "\n".join(lines)
    if args.discount is not None and not 0.0 <= args.discount < 1.0:
        return "--discount must be a fraction in [0, 1), e.g. 0.5"
    rate = parse_rate(args.rate) if args.rate else None

    days = _SINCE_DAYS[args.since]
    cutoff = None if days is None else datetime.now(timezone.utc) - timedelta(days=days)
    label = "all time" if days is None else f"last {args.since}"
    hist_path = args.history_file or hist.HISTORY_FILE
    history_rows = hist.read_history(hist_path) if (args.history or args.record) else []
    if cutoff is not None and history_rows:
        history_rows = [h for h in history_rows if h["day"] >= cutoff.date().isoformat()]

    reports, to_record = [], []
    for ad in _adapters(args.tool):
        tool_hist = [h for h in history_rows if h["tool"] == ad.tool] if args.history else None
        if not ad.available():
            if tool_hist:  # the store is gone (reset/uninstalled) but we remembered it
                reports.append(burn_report(ad.tool, ad.display_name, [], plans_for(ad.tool, cat), args.plan,
                                           label, rate=rate, discount=args.discount, by=args.by or "month",
                                           history_rows=tool_hist))
            continue
        all_evs = ad.events(since=None)
        if args.record:
            to_record += hist.daily_aggregates(all_evs, ad.tool).values()
        evs = [e for e in all_evs if cutoff is None or e.ts_utc >= cutoff]
        if args.session:
            evs = [e for e in evs if e.session_id.startswith(args.session)]
            label = f"session {args.session}"
        if not evs and not tool_hist:
            continue
        reports.append(burn_report(ad.tool, ad.display_name, evs, plans_for(ad.tool, cat), args.plan, label,
                                   rate=rate, discount=args.discount, by=args.by, history_rows=tool_hist))
    recorded = hist.upsert(to_record, hist_path) if args.record and to_record else None

    if not reports:
        return "No usage events found for this window. Run `token-finops adapters` to see what was probed."
    if args.json:
        return json.dumps({"reports": reports, "history_lines": recorded}, indent=2, default=str)
    out: list[str] = []
    for r in reports:
        if out:
            out.append("")
        out += render_burn(r, _pricing_date(), show_efficiency=args.efficiency)
    if recorded is not None:
        out.append("")
        out.append(f"history: {recorded} tool-day lines in {hist_path}")
    out.append("")
    out.append("Maxing scale: <0.5x subsidising the provider · 0.5-1x break-even-ish · 1-3x normal heavy use · "
               "3-10x token maxing · >=10x arson. Plans publish no token allowance, so this is the only "
               "honest plan-vs-API comparison; the real limit on a plan is the rolling window (see `report`).")
    return "\n".join(out)


__all__ = ["load_plans", "plans_for", "plan_equivalents", "maxing_label", "efficiency", "model_tier",
           "parse_rate", "prepaid_usd", "burn_report", "render_burn", "add_burn_parser", "cmd_burn"]
