# 04 — Local vs. Cloud

"Would a Mac Studio in the corner be cheaper?" is the question people ask right after they see their first big cloud bill. The honest answer is: sometimes, and it depends on one number most people never measure — utilisation. This chapter is the arithmetic behind `token-finops savings` and `token-finops break-even`.

## The formula

Local inference cost per million tokens has two components: energy and amortised hardware.

```
hours_per_Mtok   = 1e6 / (tok_s * 3600)
kWh_per_Mtok     = load_W * hours_per_Mtok / 1000
energy_$/Mtok    = kWh_per_Mtok * (EUR/kWh) / (EUR/USD)
capex_$/hour     = price_USD / (lifetime_hours * utilization)
capex_$/Mtok     = capex_$/hour * hours_per_Mtok
total_$/Mtok     = energy_$/Mtok + capex_$/Mtok
```

Energy cost is fixed by the hardware's power draw and the model's throughput. Capex cost is not fixed at all — it's inversely proportional to utilisation, because a machine that sits idle 23 hours a day is still depreciating for all 24.

## German constants (reviewed 2026-09-12)

Household grid electricity in Germany runs **37.0 ct/kWh** (BDEW, August 2026). If you'd run the box on your own solar instead, the honest price isn't zero — it's the feed-in tariff you give up by self-consuming instead of exporting: **7.71 ct/kWh** for systems ≤10 kWp (Aug 2026–Jan 2027). A full-cost LCOE view of small rooftop PV (≤30 kWp) ranges **6.3–14.4 ct/kWh** depending on system cost and irradiation (Fraunhofer ISE, "Levelized Cost of Electricity – Renewable Energy Technologies", July 2024); we use the midpoint, **10.4 ct/kWh**. Solar is not free power; it's power with a different, lower opportunity cost.

## Worked example: Mac Studio M4 Max + Qwen3-32B

Hardware: Mac Studio M4 Max, 128 GB, $3,999, 90 W under load. Model: Qwen3-32B (Q4), 25 tok/s on this hardware, quality tier roughly Sonnet-class for coding-agent work (an assumption, not a benchmark claim). That throughput gives ~11.1 hours per million tokens and ~1 kWh per million tokens — about $0.40/Mtok in energy at German grid rates.

Capex is where utilisation decides the outcome:

| Utilisation | Capex $/Mtok | Total local $/Mtok | Cloud (Sonnet-class, $/Mtok) | Verdict |
|---|---|---|---|---|
| 20% (a box mostly idle) | $8.46 | $8.86 | $3.20 | Cloud cheaper, by ~2.8x |
| 80% (near-continuous use) | $2.11 | $2.52 | $3.20 | Local cheaper, by ~0.79x |

The break-even point — where local and cloud cost the same — works out to roughly **60% utilisation** for this exact hardware/model/tariff combination (24/7 basis, ~14.5 hours/day of actual inference). Below that, the machine is capex-dominated and loses to the subscription; above it, the fixed cost is spread thin enough to win. Swap in solar feed-in pricing at 80% utilisation and the same box lands at about $2.20/Mtok — roughly 0.69x the cloud price — because energy cost drops but capex doesn't change at all.

## Why cache-heavy agent loops favour the cloud more than raw tokens suggest

Chapter 02 showed that a real agentic session is over 95% cache reads, priced at roughly a tenth of fresh input. A local box gets no such discount — every token of re-sent context costs full energy and full wall-clock time again, because there's no cache-read tier to bill it at. That means the token counts a cloud provider reports and the token counts a local box would need to process are not comparable one-to-one; a workload that looks cheap on the cloud specifically because it's cache-heavy will look proportionally more expensive if you move it to hardware that can't discount a re-processed prompt.

## The quality-equivalence caveat

Every number above assumes a 32B open-weight model does "Sonnet-class" coding-agent work. That's a labelled assumption in `hardware_profiles.json`, not a benchmark result — open models at this size are not frontier models, and using one to replace a state-of-the-art plan will show savings on paper and a quality regression in the diffs it produces. `token-finops break-even` only ever counts Haiku/Sonnet-tier cloud usage as "replaceable" by a local box for exactly this reason — Opus- or Fable-class work stays off the table.

## Commands

```
token-finops savings --hardware mac-studio-m4-max-128gb --model qwen3-32b --utilization 0.2
token-finops break-even --hardware mac-studio-m4-max-128gb --replaceable-tiers haiku,sonnet
```

`savings` gives you the snapshot above for any hardware/model/tariff combination in the editable JSON defaults. `break-even` replays your actual usage history and tells you, at your real pace, how many days until a local box would have already paid for itself — or whether, at current usage, it never would.

## The hybrid outlook

None of this argues for going all-local. The realistic shape for a small team is hybrid: a local model (via Ollama, or a coordinating layer like Hermes Agent) handles the high-volume, low-stakes tail of the work — exactly the "menial" bucket from chapter 03 — while the cloud plan still carries the cache-heavy, frontier-tier agent loops it's actually priced well for. And if you're going to try a fine-tuned regional model on your own hardware just to see what happens, at least make it entertaining — a Bavarian-dialect model like Llama-GENBA-10B is the kind of local experiment that costs a rounding error in electricity and earns its keep in office morale alone.
