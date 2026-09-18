"""Local-vs-cloud savings estimator and the "from now on a local box would be
cheaper" break-even tracker.

Honesty rules baked in:
- electricity from your own solar is priced at the feed-in tariff you forgo,
  not at zero;
- capex is amortised per hour of *actual* utilisation — a $4k Mac Studio at
  20 % utilisation is capex-dominated and loses to Sonnet; at 80 % it wins;
- only tokens on cloud tiers a local model can plausibly replace (haiku /
  sonnet class) are counted as "replaceable"; Opus/Fable-class work is not;
- if you already own the box, its purchase price is a sunk cost — `--own-hardware`
  drops capex entirely and compares the *marginal* cost of a token instead;
- the local CO2 figure is arithmetic on a published grid-mix number; the cloud
  CO2 figure is an order-of-magnitude *estimate* built from third-party inference
  energy studies, because no cloud AI provider publishes Wh per token. The two
  are never printed as if they were the same kind of number — see
  `docs/CO2_ESTIMATE.md`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

_HERE = os.path.dirname(__file__)


def _load(name: str, override_env: str) -> dict:
    path = os.environ.get(override_env) or os.path.join(_HERE, name)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def hardware_profiles() -> dict:
    return _load("hardware_profiles.json", "TOKEN_FINOPS_HARDWARE_JSON")


def energy() -> dict:
    return _load("energy.json", "TOKEN_FINOPS_ENERGY_JSON")


# --------------------------------------------------------------------------- #
@dataclass
class LocalCost:
    hardware: str
    model: str
    tok_s: float
    load_w: float
    price_usd: float
    lifetime_years: float
    utilization: float
    tariff: str
    eur_per_kwh: float
    eur_per_usd: float
    include_capex: bool = True
    management_overhead: float = 0.0   # only meaningful when include_capex is False -- see --own-hardware

    @property
    def hours_per_mtok(self) -> float:
        return 1e6 / (self.tok_s * 3600.0)

    @property
    def kwh_per_mtok(self) -> float:
        return self.load_w * self.hours_per_mtok / 1000.0

    @property
    def wh_per_1k_tok(self) -> float:
        return self.kwh_per_mtok  # numerically identical (kWh/MTok == Wh/kTok)

    @property
    def energy_usd_per_mtok(self) -> float:
        return self.kwh_per_mtok * self.eur_per_kwh / self.eur_per_usd

    @property
    def capex_usd_per_hour(self) -> float:
        if not self.include_capex:
            return 0.0
        lifetime_h = self.lifetime_years * 365 * 24
        return self.price_usd / (lifetime_h * max(self.utilization, 1e-6))

    @property
    def capex_usd_per_mtok(self) -> float:
        return self.capex_usd_per_hour * self.hours_per_mtok

    # --- CO2 ---------------------------------------------------------------- #
    @property
    def co2_g_per_kwh(self) -> Optional[float]:
        v = energy().get("co2_g_per_kwh", {}).get(self.tariff)
        return float(v) if v else None

    @property
    def co2_g_per_mtok(self) -> Optional[float]:
        g = self.co2_g_per_kwh
        return None if g is None else self.kwh_per_mtok * g

    @property
    def management_usd_per_mtok(self) -> float:
        """Flat percentage of energy cost, standing in for wear/maintenance/occasional
        troubleshooting on hardware you already own. This is an ASSUMPTION, not a sourced
        figure -- there is no citable per-token maintenance-cost dataset -- so it is always
        printed alongside its own line rather than folded silently into the total. Only
        meaningful once capex is off the table (--own-hardware); a capex-amortized total
        already spreads the box's own upkeep-adjacent risk across its purchase price."""
        if self.include_capex:
            return 0.0
        return self.energy_usd_per_mtok * self.management_overhead

    @property
    def total_usd_per_mtok(self) -> float:
        return self.energy_usd_per_mtok + self.capex_usd_per_mtok + self.management_usd_per_mtok

    def break_even_utilization(self, cloud_usd_per_mtok: float) -> Optional[float]:
        """Utilisation at which local == cloud (None if energy alone already costs more,
        or if capex is excluded — with a sunk-cost box there is nothing to break even on)."""
        margin = cloud_usd_per_mtok - self.energy_usd_per_mtok
        if margin <= 0 or not self.include_capex:
            return None
        lifetime_h = self.lifetime_years * 365 * 24
        return min(1.0, self.price_usd * self.hours_per_mtok / (lifetime_h * margin))


def local_cost(hardware: str, model: str, tariff: str = "grid-de-household",
               utilization: float = 0.2, lifetime_years: float = 3.0,
               include_capex: bool = True, management_overhead: float = 0.0) -> LocalCost:
    hw = hardware_profiles()
    en = energy()
    h = hw["hardware"][hardware]
    m = hw["models"][model]
    if hardware not in m["tok_s"]:
        raise KeyError(f"no throughput figure for {model} on {hardware}; add one to hardware_profiles.json")
    t = en["tariffs"][tariff]
    return LocalCost(hardware=hardware, model=model, tok_s=float(m["tok_s"][hardware]),
                     load_w=float(h["load_w"]), price_usd=float(h["price_usd"]),
                     lifetime_years=lifetime_years, utilization=utilization, tariff=tariff,
                     eur_per_kwh=float(t["eur_per_kwh"]), eur_per_usd=float(en["eur_per_usd"]),
                     include_capex=include_capex, management_overhead=management_overhead)


def cloud_blended_usd_per_mtok(tier: str, output_share: float = 0.15) -> float:
    """Blend input/output list prices with a typical coding-agent output share."""
    t = energy()["cloud_tiers_usd_per_mtok"][tier]
    return t["input"] * (1 - output_share) + t["output"] * output_share


# --------------------------------------------------------------------------- #
# Cloud-side CO2 — an ESTIMATE, and labelled as one everywhere it surfaces.
# --------------------------------------------------------------------------- #
@dataclass
class CloudCo2Estimate:
    """Order-of-magnitude gCO2e per 1M cloud tokens.

    This is *not* the same kind of number as `LocalCost.co2_g_per_mtok`. The local
    side multiplies a wattmeter reading by a published grid-mix figure. No cloud AI
    provider publishes Wh per token, so this side multiplies a third-party estimate
    of accelerator-level inference energy by a published fleet PUE and a published
    grid carbon intensity. Treat it as a rough magnitude, not a measurement —
    `docs/CO2_ESTIMATE.md` carries every source and the error bars.
    """
    region: str
    region_label: str
    region_source: str
    wh_per_mtok_it: float
    pue: float
    pue_label: str
    g_co2_per_kwh: float
    confidence: str
    basis: str

    @property
    def kwh_per_mtok(self) -> float:
        return self.wh_per_mtok_it * self.pue / 1000.0

    @property
    def g_co2_per_mtok(self) -> float:
        return self.kwh_per_mtok * self.g_co2_per_kwh


def cloud_co2_estimate(region: Optional[str] = None) -> Optional[CloudCo2Estimate]:
    """Build the cloud-side estimate from energy.json, or None if that block is absent
    (a user pointing TOKEN_FINOPS_ENERGY_JSON at an older file simply gets no cloud line)."""
    blk = energy().get("cloud_inference_co2_estimate")
    if not blk:
        return None
    region = region or blk["default_region"]
    if region not in blk["regions"]:
        raise KeyError(f"unknown --cloud-region {region!r}; known: {', '.join(blk['regions'])}")
    r = blk["regions"][region]
    return CloudCo2Estimate(region=region, region_label=r["label"], region_source=r["source"],
                            wh_per_mtok_it=float(blk["wh_per_mtok_it"]), pue=float(blk["pue"]),
                            pue_label=blk["pue_label"], g_co2_per_kwh=float(r["g_co2_per_kwh"]),
                            confidence=blk["confidence"], basis=blk["basis"])


# --------------------------------------------------------------------------- #
# CLI glue
# --------------------------------------------------------------------------- #
def add_savings_parsers(sub):
    s = sub.add_parser("savings", help="local $/MTok vs cloud tier for a hardware+model combo")
    s.add_argument("--hardware", default="mac-studio-m4-max-128gb")
    s.add_argument("--model", default="qwen3-32b")
    s.add_argument("--power", default="grid-de-household", help="tariff key from energy.json (e.g. solar-de-feed-in)")
    s.add_argument("--utilization", type=float, default=0.2, help="fraction of 24/7 the box is actually inferring")
    s.add_argument("--lifetime-years", type=float, default=3.0)
    s.add_argument("--output-share", type=float, default=0.15, help="share of output tokens in the cloud blend")
    s.add_argument("--own-hardware", action="store_true",
                   help="you already own the box: treat its price as sunk and compare marginal (energy-only) cost")
    s.add_argument("--management-overhead", type=float, default=0.10,
                   help="with --own-hardware: flat fraction of energy cost added as a running-cost "
                        "assumption (wear, maintenance, occasional troubleshooting) -- default 0.10 (10%%); "
                        "not a sourced figure, always shown on its own line")
    s.add_argument("--co2", action="store_true",
                   help="green-IT block: local gCO2/1M tok (measured tariff) vs an ESTIMATED cloud figure")
    s.add_argument("--cloud-region", default=None,
                   help="grid region for the cloud CO2 estimate (see --list); default from energy.json")
    s.add_argument("--list", action="store_true", help="list hardware/model/tariff keys")

    b = sub.add_parser("break-even", help="from your real usage: when would a local box have paid off?")
    b.add_argument("--hardware", default="mac-studio-m4-max-128gb")
    b.add_argument("--model", default="qwen3-32b")
    b.add_argument("--power", default="grid-de-household")
    b.add_argument("--lifetime-years", type=float, default=3.0)
    b.add_argument("--replaceable-tiers", default="haiku,sonnet",
                   help="cloud tiers a local model could plausibly replace")
    b.add_argument("--tool", action="append", default=None, help="restrict to tool(s); default all")
    b.add_argument("--since", default="all", choices=["30d", "90d", "all"])


def _green_it_block(lc: LocalCost, region: Optional[str]) -> list:
    """The opt-in `--co2` section. Deliberately prints the provenance of each side on
    its own line, because the two numbers are not equally trustworthy and a reader who
    only sees 'local 380 g vs cloud 120 g' would draw a conclusion the cloud figure
    cannot support."""
    en = energy()
    out = ["Green IT: gCO2e per 1M tokens (energy only -- capex/embodied emissions are NOT in either figure)"]
    local_g = lc.co2_g_per_mtok
    if local_g is None:
        out.append(f"  local:  n/a           -- no co2_g_per_kwh entry for tariff '{lc.tariff}' in energy.json")
    else:
        out.append(f"  local:  ~{local_g:>6.0f} g   [computed]  {lc.kwh_per_mtok:.2f} kWh/1M tok x {lc.co2_g_per_kwh:.0f} g/kWh")
        out.append(f"                      {en['tariffs'][lc.tariff]['label']}")
    est = cloud_co2_estimate(region)
    if est is None:
        out.append("  cloud:  n/a           -- no cloud_inference_co2_estimate block in energy.json")
        return out
    out.append(f"  cloud:  ~{est.g_co2_per_mtok:>6.0f} g   [ESTIMATE]  {est.wh_per_mtok_it:.0f} Wh/1M tok accelerator-side"
               f" x PUE {est.pue:.2f} x {est.g_co2_per_kwh:.0f} g/kWh")
    out.append(f"                      {est.region_label}; {est.pue_label}")
    if local_g is not None and est.g_co2_per_mtok:
        r = local_g / est.g_co2_per_mtok
        out.append(f"  -> local emits ~{r:.1f}x the cloud estimate per token"
                   if r >= 1 else f"  -> local emits ~{r:.2f}x the cloud estimate per token (local is cleaner)")
    out.append("  !! The cloud figure is an ORDER-OF-MAGNITUDE ESTIMATE, not a measurement. No cloud AI provider")
    out.append(f"     publishes energy per token. Basis: {est.basis}")
    out.append(f"     Confidence: {est.confidence}")
    out.append(f"     Grid figure: {est.region_source}")
    out.append("     Every source, and why the error bars are this wide: docs/CO2_ESTIMATE.md")
    return out


def cmd_savings(args) -> str:
    hw, en = hardware_profiles(), energy()
    if args.list:
        lines = ["hardware:"] + [f"  {k:<28} {v['label']}  (${v['price_usd']}, {v['load_w']} W load)" for k, v in hw["hardware"].items()]
        lines += ["models:"] + [f"  {k:<28} {v['label']}  ~{v['quality_tier']}-class" for k, v in hw["models"].items() if not k.startswith('_')]
        lines += ["tariffs:"] + [f"  {k:<28} {v['eur_per_kwh']:.3f} EUR/kWh  {v['label']}" for k, v in en["tariffs"].items()]
        blk = en.get("cloud_inference_co2_estimate")
        if blk:
            lines += ["cloud regions (--cloud-region, CO2 estimate only):"] + \
                [f"  {k:<28} {v['g_co2_per_kwh']:.0f} gCO2/kWh  {v['label']}" for k, v in blk["regions"].items()]
        return "\n".join(lines)
    own = bool(getattr(args, "own_hardware", False))
    lc = local_cost(args.hardware, args.model, args.power, args.utilization, args.lifetime_years,
                    include_capex=not own,
                    management_overhead=getattr(args, "management_overhead", 0.10) if own else 0.0)
    tier = hw["models"][args.model]["quality_tier"]
    cloud = cloud_blended_usd_per_mtok(tier, args.output_share)
    lines = [f"Local inference: {hw['hardware'][args.hardware]['label']} + {hw['models'][args.model]['label']}"]
    lines.append(f"  throughput:        {lc.tok_s:.0f} tok/s  ->  {lc.hours_per_mtok:.2f} h per 1M tokens")
    lines.append(f"  energy:            {lc.load_w:.0f} W load  ->  {lc.wh_per_1k_tok:.2f} Wh per 1k tok, {lc.kwh_per_mtok:.2f} kWh per 1M tok")
    lines.append(f"  tariff:            {en['tariffs'][args.power]['label']} = {lc.eur_per_kwh:.3f} EUR/kWh")
    lines.append(f"  energy cost:       ${lc.energy_usd_per_mtok:.2f} / 1M tok")
    if own:
        lines.append(f"  capex:             EXCLUDED (--own-hardware): ${lc.price_usd:,.0f} is sunk, "
                     "so only the marginal cost of the next token counts")
        lines.append(f"  running overhead:  +{lc.management_overhead*100:.0f}% of energy cost = ${lc.management_usd_per_mtok:.2f} / 1M tok"
                     "  [ASSUMPTION -- wear/maintenance, not a sourced figure; --management-overhead to change]")
    else:
        lines.append(f"  capex:             ${lc.price_usd:,.0f} over {lc.lifetime_years:.0f} y at {lc.utilization*100:.0f}% utilisation"
                     f" = ${lc.capex_usd_per_hour:.3f}/h -> ${lc.capex_usd_per_mtok:.2f} / 1M tok")
    label = "hosting (local):  " if own else "local total:      "
    lines.append(f"  {label} ${lc.total_usd_per_mtok:.2f} / 1M tok")
    lines.append("")
    cloud_label = "Licensing (cloud)" if own else "Cloud comparison"
    lines.append(f"{cloud_label} ({tier}-class, {args.output_share*100:.0f}% output tokens): ${cloud:.2f} / 1M tok  ({en['cloud_tiers_usd_per_mtok'][tier]['label']})")
    ratio = lc.total_usd_per_mtok / cloud if cloud else float("inf")
    if own:
        verdict = "HOSTING CHEAPER" if ratio < 1 else "LICENSING CHEAPER"
        lines.append(f"  -> hosting is {ratio:.2f}x the licensing price: {verdict}")
        lines.append("  -> sunk-cost view: no break-even to reach, the box is already bought; "
                     f"this is electricity + {lc.management_overhead*100:.0f}% running overhead vs. the API/plan bill")
    else:
        verdict = "LOCAL CHEAPER" if ratio < 1 else "CLOUD CHEAPER"
        lines.append(f"  -> local is {ratio:.2f}x the cloud price: {verdict}")
        be = lc.break_even_utilization(cloud)
        if be is None:
            lines.append("  -> energy alone already exceeds the cloud price; no utilisation makes this box win")
        else:
            lines.append(f"  -> break-even utilisation: {be*100:.0f}% of 24/7 ({be*24:.1f} h/day of inference)")
    green = bool(getattr(args, "co2", False))
    if lc.co2_g_per_mtok is not None and not green:
        lines.append(f"  CO2: ~{lc.co2_g_per_mtok:.0f} g per 1M tok on this tariff  (--co2 adds the cloud comparison)")
    if green:
        lines += ["", *_green_it_block(lc, getattr(args, "cloud_region", None))]
    lines.append("")
    lines.append("Caveats: throughput/power figures are editable defaults (see hardware_profiles.json, "
                 f"reviewed {hw['_review_date']}); quality equivalence is an assumption; a {tier}-class local "
                 "model does not replace Opus/Fable-class work.")
    return "\n".join(lines)


def cmd_break_even(args) -> str:
    """Replay real usage: cumulative cloud-equivalent spend on *replaceable* tiers
    vs. the cumulative cost of owning + running the local box since first use."""
    from ..adapters import all_adapters
    from ..core.pricing import lookup

    hw, en = hardware_profiles(), energy()
    tiers = {t.strip() for t in args.replaceable_tiers.split(",") if t.strip()}
    tier_prices = en["cloud_tiers_usd_per_mtok"]

    def tier_of(model_norm: str) -> Optional[str]:
        for t in ("haiku", "sonnet", "opus", "fable"):
            if t in model_norm:
                return t
        return None

    now = datetime.now(timezone.utc)
    since = None
    if args.since != "all":
        since = now - timedelta(days=int(args.since[:-1]))
    events = []
    for ad in all_adapters():
        if args.tool and ad.tool not in args.tool:
            continue
        if ad.available():
            events += ad.events(since)
    events.sort(key=lambda e: e.ts_utc)
    if not events:
        return "No usage events found to replay."

    # daily cloud-equivalent spend on replaceable tiers
    daily: dict = {}
    replaceable_tokens = 0
    total_cloud = 0.0
    for e in events:
        t = tier_of(e.model_norm)
        if t not in tiers:
            continue
        if e.usd_estimate is not None:
            usd = e.usd_estimate  # adapter priced it with real cache-read/write rates
        else:
            p = lookup(e.model_raw) or {"input": tier_prices[t]["input"], "output": tier_prices[t]["output"]}
            usd = (e.input_tokens + e.cache_write_tokens) * p["input"] / 1e6 \
                + e.cache_read_tokens * p["input"] * 0.1 / 1e6 + e.output_tokens * p["output"] / 1e6
        daily[e.ts_utc.date()] = daily.get(e.ts_utc.date(), 0.0) + usd
        replaceable_tokens += e.total_tokens
        total_cloud += usd
    if not daily:
        return f"No usage on replaceable tiers ({', '.join(sorted(tiers))}) in the selected range."

    first_day = min(daily)
    days = (now.date() - first_day).days + 1
    lc_ref = local_cost(args.hardware, args.model, args.power, utilization=1.0, lifetime_years=args.lifetime_years)
    # local running cost for the same tokens: energy per token + fixed capex per elapsed day
    energy_usd = replaceable_tokens / 1e6 * lc_ref.energy_usd_per_mtok
    capex_per_day = lc_ref.price_usd / (lc_ref.lifetime_years * 365)
    capex_usd = capex_per_day * days
    local_total = energy_usd + capex_usd

    # projected break-even at recent burn
    recent = [v for d, v in daily.items() if d >= now.date() - timedelta(days=14)]
    burn_per_day = sum(recent) / 14.0 if recent else total_cloud / max(days, 1)
    energy_per_day_local = (replaceable_tokens / max(days, 1)) / 1e6 * lc_ref.energy_usd_per_mtok
    net_per_day = burn_per_day - energy_per_day_local - capex_per_day
    lines = [f"Break-even replay: {hw['hardware'][args.hardware]['label']} running {hw['models'][args.model]['label']} "
             f"since {first_day} ({days} days)"]
    lines.append(f"  replaceable cloud usage ({', '.join(sorted(tiers))}-class): {replaceable_tokens/1e6:.1f}M tokens "
                 f"= ${total_cloud:,.2f} API-equivalent")
    lines.append(f"  local alternative:  energy ${energy_usd:,.2f} + capex ${capex_usd:,.2f} "
                 f"(${capex_per_day:.2f}/day straight-line over {args.lifetime_years:.0f} y) = ${local_total:,.2f}")
    if total_cloud >= local_total:
        lines.append(f"  -> LOCAL WOULD ALREADY BE CHEAPER by ${total_cloud - local_total:,.2f}")
    else:
        gap = local_total - total_cloud
        if net_per_day > 0:
            eta = gap / net_per_day
            lines.append(f"  -> cloud still cheaper by ${gap:,.2f}; at the last-14-day pace (${burn_per_day:.2f}/day) "
                         f"local overtakes in ~{eta:.0f} days ({(now + timedelta(days=eta)).date()})")
        else:
            lines.append(f"  -> cloud still cheaper by ${gap:,.2f}; at the current pace (${burn_per_day:.2f}/day) "
                         "the box never pays off within its lifetime")
    lines.append("")
    lines.append("Assumptions: only haiku/sonnet-class calls are considered replaceable (edit with "
                 "--replaceable-tiers); cloud side uses real cache-read/write pricing; the local box has "
                 "no cache discount but re-processes cached context at full energy cost — that is why "
                 "cache-heavy agent loops favour the cloud more than raw token counts suggest.")
    return "\n".join(lines)
