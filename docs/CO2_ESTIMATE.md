# `token-finops savings --co2` — gCO2e per 1M tokens, local vs. cloud

```
$ token-finops savings --co2 --hardware macbook-pro-16-m4-max-48gb --power solar-de-feed-in --cloud-region us-gas-heavy

Green IT: gCO2e per 1M tokens (energy only -- capex/embodied emissions are NOT in either figure)
  local:  ~    38 g   [computed]  0.95 kWh/1M tok x 40 g/kWh
                      Germany PV self-consumption, opportunity cost = feed-in tariff <=10 kWp
  cloud:  ~   259 g   [ESTIMATE]  500 Wh/1M tok accelerator-side x PUE 1.15 x 450 g/kWh
                      US datacentre region with a gas-dominated mix (ERCOT/PJM-class, approx.)
  -> local emits ~0.15x the cloud estimate per token (local is cleaner)
  !! The cloud figure is an ORDER-OF-MAGNITUDE ESTIMATE, not a measurement. ...
```

The two numbers on that screen are **not the same kind of number**, and the output says so
on every line rather than in a footnote. This page explains why, and where each figure
comes from.

## The honesty problem

This repo already has one number it cannot source cleanly: GitHub Copilot's effective
$/token, which no one publishes, so [`COST_PER_TOKEN.md`](COST_PER_TOKEN.md) renders it as
a *derived* rate with a `*` and a legend instead of quietly presenting it as a price. The
cloud-side CO2 figure is the same problem in a different unit, and gets the same treatment:

| | local side | cloud side |
|---|---|---|
| tag in output | `[computed]` | `[ESTIMATE]` |
| energy | your box's `load_w` from `hardware_profiles.json` — a number you can replace with your own wattmeter reading | a third party's estimate of what *somebody else's* accelerators draw |
| carbon intensity | published grid-mix figure for a tariff you actually pay | published grid-mix figure for a datacentre region you are guessing at |
| honest error bar | a few tens of percent (throughput and power draw vary with model and quantisation) | **roughly a factor of 3 in either direction** |

`--co2` is **opt-in**. Without it, `savings` prints only the single-line local CO2 figure
it always printed, plus a pointer to the flag. That is deliberate: the cloud figure is
weak enough that it should be something you ask for, not something the tool volunteers.

## How the cloud figure is built

```
gCO2e per 1M cloud tokens  =  Wh_per_Mtok_accelerator  x  PUE  x  gCO2/kWh_grid
                           =  500 Wh                   x  1.15 x  390 g/kWh  (us-avg)
                           ≈  224 g
```

All three inputs live in `savings/energy.json` under `cloud_inference_co2_estimate`, so
you can replace any of them without touching code (or point `TOKEN_FINOPS_ENERGY_JSON` at
your own copy).

### 1. ~500 Wh per 1M tokens, accelerator-side — **estimate, low confidence**

No cloud AI provider — Anthropic, OpenAI, Google, AWS — publishes energy per token. What
does exist is a handful of published **per-query** figures, which have to be divided by an
assumed response length to become per-token:

| Source | Figure | Note |
|---|---|---|
| Google, *Measuring the environmental impact of delivering AI products* (2025) | median Gemini text prompt ≈ **0.24 Wh**, ≈ 0.03 gCO2e | The most directly relevant published number. Google states it covers the full serving stack, not just the accelerator. |
| Epoch AI (2025), GPT-4o-class query estimate | ≈ **0.3 Wh** per query | Independent reconstruction from model size and serving assumptions. |
| de Vries, *The growing energy footprint of AI*, Joule (2023) | ≈ **2.9 Wh** per ChatGPT query | Widely cited and widely considered an over-estimate today; serving efficiency improved substantially after it was written. Using it would push this figure ~6x higher. |

Taking the two more recent figures (~0.25–0.3 Wh/query) and dividing by an assumed
**~500 output tokens per query** gives ~0.5 Wh per 1k tokens, i.e. **~500 Wh per 1M
tokens**. Every step of that is soft:

- **the response length is an assumption.** A 200-token answer and a 2,000-token answer
  cost very different amounts of energy for the same "query". Coding-agent traffic skews
  long, which would push the per-query figure up but the per-*token* figure down.
- **decode dominates, prefill is cheap.** These per-token figures are really per-*output*-
  token. `savings` compares against a blended input+output token count, so the cloud side
  is, if anything, conservative (pessimistic about the cloud).
- **model size is unknown.** A Haiku-class model and an Opus-class model do not cost the
  same per token, and no provider breaks this out.
- **batching and hardware generation** swing serving efficiency by multiples.

This is why the output prints `Confidence: LOW -- good to roughly a factor of 3 either
way`, and why the number is deliberately round (500, not 487).

### 2. PUE 1.15 — **estimate, medium confidence**

Power Usage Effectiveness: total facility power divided by IT power, i.e. the cooling and
distribution overhead on top of the chips. The three largest cloud providers publish
fleet-wide figures in their annual sustainability reports, clustered around Google ~1.09,
AWS ~1.15, Microsoft ~1.18. **1.15** is the midpoint used here.

This is the least uncertain input — hyperscale PUE is a well-measured, publicly reported
metric, and the spread between providers is small enough that it barely moves the result.
Note that the Google 0.24 Wh figure above already includes overhead, so applying PUE on
top of it double-counts slightly; that is one more reason the output is rounded and
flagged rather than presented to three significant figures.

### 3. Grid carbon intensity — **approximate, and region-dependent**

`--cloud-region` picks which grid the cloud tokens are assumed to burn on:

| key | gCO2/kWh | what it is |
|---|---|---|
| `us-avg` (default) | 390 | The commonly-cited **EPA eGRID-class US national average** (~0.85 lb CO2/kWh). Approximate; not re-verified against the latest eGRID release. |
| `us-gas-heavy` | 450 | A US datacentre region where **gas sets most of the marginal generation** — the "the AI industry runs on gas" framing. A modern combined-cycle gas plant emits roughly 350–400 gCO2/kWh at the plant; a grid leaning on gas at the margin lands somewhat above that. **This is a representative figure, not a published number for any named balancing authority** (ERCOT, PJM, Dominion). |
| `de-grid` | 380 | The German grid mix — the same figure as the `grid-de-household` tariff. Use it to compare cloud vs. local hardware **on the same grid**, which isolates the hardware-efficiency difference from the grid-mix difference. |

The local-side tariff carbon intensities (`co2_g_per_kwh` in `energy.json`) are unchanged
by this work and keep their existing provenance: 380 g/kWh for the German grid mix, 390
for the US average, 40 g/kWh lifecycle emissions for rooftop PV (Fraunhofer ISE / BDEW
class figures — see [`sources.md`](sources.md)). The German figure is on the pessimistic
side: the German grid has been decarbonising quickly and a current official
Umweltbundesamt figure may be meaningfully lower, which would make the local side look
*better* than it does here.

## What the numbers are NOT

- **Not embodied carbon.** Neither side counts manufacturing. A MacBook Pro's embodied
  emissions are on the order of a few hundred kg CO2e — for a lightly-used box that can
  dwarf its operational emissions over three years, and it is entirely absent from both
  columns. The output says `energy only` on the header line for exactly this reason.
- **Not water.** Datacentre water consumption is a real and separate impact, not modelled.
- **Not a claim about any specific provider.** Nothing here is an Anthropic, OpenAI,
  Google or AWS figure. Do not quote it as one.
- **Not a licence to greenwash either direction.** On the default settings a desktop Mac
  Studio on the German grid emits roughly **1.6x** the cloud estimate per token, because a
  hyperscale datacentre batches work across many users and a box on your desk does not.
  Local inference wins on carbon mainly when it runs on your own PV, not by default.

## Why the cloud estimate is worth shipping at all

Because the alternative is worse. Without it, `savings` printed a local CO2 number with
nothing to compare it against, which invites the reader to assume the cloud side is either
zero or enormous depending on their priors. A labelled order-of-magnitude figure with
visible error bars is more honest than a conspicuous blank — as long as it never pretends
to be a measurement, which is what the `[ESTIMATE]` tag, the confidence line, and the
basis line in the output are for.

## Re-sourcing it yourself

Everything is editable JSON with a review date:

```bash
$ token-finops savings --list          # includes the cloud regions
$ export TOKEN_FINOPS_ENERGY_JSON=./my-energy.json
```

If you have a better-sourced per-token energy figure — especially a provider-published one
— replace `wh_per_mtok_it` and its `_source` string and open a PR. Per
[`AGENTS.md`](../AGENTS.md) rule 6, every number in this repo carries a source and a review
date; this one carries the honest admission that its source is an inference from somebody
else's per-query estimate.

## See also

- [`COST_PER_TOKEN.md`](COST_PER_TOKEN.md) — the same real-vs-derived honesty split, for $/token.
- [`sources.md`](sources.md) — every price, tariff and grid figure with its source and review date.
- `savings/energy.json`, `savings/hardware_profiles.json` — the data behind all of it.
