"""`token-finops cost-per-token` — $ per 1M tokens, per tool and per model.

Two different numbers show up side by side here, and they must not be confused:

- **list price** — `core/pricing.py`'s $/Mtok table: what the model costs on a
  pay-per-token API key. This is a real, provider-published rate. It applies to every
  adapter that already computes `usd_estimate` off that table: Claude Code, Codex,
  Gemini CLI, Hermes (OpenRouter), OpenCode, Cline/Roo/Kilo, Aider, Continue.dev.
- **derived rate** — for a tool that does not bill per token at all, this is the
  native cost (converted to USD where the conversion is fixed) divided by the tokens
  observed for that model. It is *this tool's arithmetic*, not a number the provider
  publishes or guarantees, and it is always marked with a trailing `*` plus a legend.

GitHub Copilot is the reason this distinction exists. Short answer to "does cost-per-
token work for GitHub's AI tokens": **no, not as an official rate** — Copilot bills in
AI credits / premium requests (`total_nano_aiu`; 1 credit = $0.01), and the credit cost
of a request is set by a per-model *request multiplier*, not by how many tokens went in
or out. A short reply from a frontier model and a long reply from a cheap one can cost
the same number of credits. GitHub has never published a $/token or credits/token rate,
so there is nothing "real" to report for Copilot here — only the derived ratio (credits
spent -> USD at $0.01/credit -> divided by observed tokens), which will drift with your
model mix and is a personal reference point, not a price list.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from .core.model import Unit
from .core.pricing import lookup
from .report import fmt_tokens

_SINCE_DAYS = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365, "all": None}

# Fixed, known $ conversions for native units. PERCENT/REQUESTS/MINUTES/TOKENS have no
# fixed $ conversion and are intentionally left out (None).
_AIU_USD_PER_CREDIT = 0.01  # GitHub Copilot: 1 AI credit = $0.01 (see adapters/copilot.py)


def _native_usd(native_cost: Optional[float], native_unit: Optional[Unit]) -> Optional[float]:
    if native_cost is None or native_unit is None:
        return None
    if native_unit == Unit.USD:
        return native_cost
    if native_unit == Unit.AIU:
        return native_cost * _AIU_USD_PER_CREDIT
    return None


def per_model_rows(events, tool: str) -> list[dict]:
    """One row per model actually seen, aggregated across `events`."""
    groups: dict[str, dict] = {}
    for e in events:
        key = e.model_norm or "unknown"
        g = groups.setdefault(key, {
            "tool": tool, "model": key, "calls": 0, "input": 0, "output": 0,
            "cache_read": 0, "cache_write": 0, "tokens": 0,
            "usd_priced": 0.0, "has_priced": False,
            "usd_native": 0.0, "has_native": False,
        })
        g["calls"] += 1
        g["input"] += e.input_tokens
        g["output"] += e.output_tokens
        g["cache_read"] += e.cache_read_tokens
        g["cache_write"] += e.cache_write_tokens
        g["tokens"] += e.total_tokens
        if e.usd_estimate is not None:
            g["usd_priced"] += e.usd_estimate
            g["has_priced"] = True
        nu = _native_usd(e.native_cost, e.native_unit)
        if nu is not None:
            g["usd_native"] += nu
            g["has_native"] = True
    rows = []
    for g in groups.values():
        p = lookup(g["model"])
        g["list_price_in"] = p.get("input") if p else None
        g["list_price_out"] = p.get("output") if p else None
        g["realized_usd_per_mtok"] = (
            g["usd_priced"] / g["tokens"] * 1e6 if g["has_priced"] and g["tokens"] else None
        )
        # Only "derived" when there is no real per-token price at all for this model's
        # calls — otherwise `realized` above already is the honest number.
        g["derived_usd_per_mtok"] = (
            g["usd_native"] / g["tokens"] * 1e6
            if (g["has_native"] and not g["has_priced"] and g["tokens"]) else None
        )
        rows.append(g)
    return sorted(rows, key=lambda r: -r["tokens"])


def render_cost_per_token(display_name: str, tool: str, rows: list[dict], since_label: str) -> list[str]:
    out = [f"{display_name} ({since_label}) -- $ per 1M tokens"]
    if not rows:
        out.append("  no usage events in this window")
        return out
    out.append(f"  {'model':<26} {'calls':>7} {'tokens':>9} {'list in/out':>13} {'realized':>10} {'derived':>10}")
    any_derived = False
    for r in rows:
        list_price = (f"{r['list_price_in']:.2f}/{r['list_price_out']:.2f}"
                      if r["list_price_in"] is not None else "n/a")
        realized = f"${r['realized_usd_per_mtok']:.2f}" if r["realized_usd_per_mtok"] is not None else "n/a"
        if r["derived_usd_per_mtok"] is not None:
            derived = f"${r['derived_usd_per_mtok']:.2f}*"
            any_derived = True
        else:
            derived = ""
        out.append(f"  {r['model']:<26} {r['calls']:>7} {fmt_tokens(r['tokens']):>9} "
                   f"{list_price:>13} {realized:>10} {derived:>10}")
    if any_derived:
        note = ("derived from AI-credit billing (1 credit = $0.01) divided by observed tokens"
               if tool == "copilot" else
               "derived from this tool's native cost divided by observed tokens")
        out.append(f"  * {note} -- not an official per-token price; it drifts with your model mix.")
    return out


def _rows_to_json(rows: list[dict]) -> list[dict]:
    keep = ("tool", "model", "calls", "input", "output", "cache_read", "cache_write", "tokens",
           "list_price_in", "list_price_out", "realized_usd_per_mtok", "derived_usd_per_mtok")
    return [{k: r[k] for k in keep} for r in rows]


# --------------------------------------------------------------------------- #
# CLI glue
# --------------------------------------------------------------------------- #
def add_cost_per_token_parser(sub):
    c = sub.add_parser("cost-per-token",
                       help="$ per 1M tokens by model -- real list price, or a derived rate "
                            "for AI-credit-billed tools like Copilot")
    c.add_argument("--tool", action="append", default=None, help="restrict to tool(s)")
    c.add_argument("--since", choices=["1d", "7d", "30d", "90d", "365d", "all"], default="30d")
    c.add_argument("--json", action="store_true")


def cmd_cost_per_token(args) -> str:
    from .cli import _adapters, _pricing_date

    days = _SINCE_DAYS[args.since]
    cutoff = None if days is None else datetime.now(timezone.utc) - timedelta(days=days)
    label = "all time" if days is None else f"last {args.since}"

    reports = []
    for ad in _adapters(args.tool):
        if not ad.available():
            continue
        evs = ad.events(since=None)
        evs = [e for e in evs if cutoff is None or e.ts_utc >= cutoff]
        if not evs:
            continue
        reports.append((ad, per_model_rows(evs, ad.tool)))

    if not reports:
        return "No usage events found for this window. Run `token-finops adapters` to see what was probed."
    if args.json:
        payload = [{"tool": ad.tool, "display_name": ad.display_name, "rows": _rows_to_json(rows)}
                  for ad, rows in reports]
        return json.dumps(payload, indent=2, default=str)
    out: list[str] = []
    for ad, rows in reports:
        if out:
            out.append("")
        out += render_cost_per_token(ad.display_name, ad.tool, rows, label)
    out.append("")
    out.append(f"list prices reviewed {_pricing_date()} (see core/pricing.py, override "
              "~/.token-finops/pricing.json). `realized` blends input/output/cache at the actual "
              "mix; `derived` (marked *) is this tool's own arithmetic, not a provider rate.")
    return "\n".join(out)


__all__ = ["per_model_rows", "render_cost_per_token", "add_cost_per_token_parser", "cmd_cost_per_token"]
