# `token-finops savings --co2` — gCO2e per 1M tokens, local vs. cloud

```
$ token-finops savings --co2 --hardware macbook-pro-16-m4-max-48gb --power solar-de-feed-in --cloud-region us-ercot

Green IT: gCO2e per 1M tokens (energy only -- capex/embodied emissions are NOT in either figure)
  local:  ~    38 g   [computed]  0.95 kWh/1M tok x 40 g/kWh
                      Germany PV self-consumption, opportunity cost = feed-in tariff <=10 kWp
  cloud:  ~   226 g   [ESTIMATE]  600 Wh/1M tok accelerator-side x PUE 1.13 x 334 g/kWh
                      Texas / ERCOT (eGRID ERCT) -- gas-heavy but near the US average
  -> local emits ~0.18x the cloud estimate per token (local is cleaner)
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
                           =  600 Wh                   x  1.13 x  350 g/kWh  (us-avg)
                           ≈  237 g
```

All three inputs live in `savings/energy.json` under `cloud_inference_co2_estimate`, so
you can replace any of them without touching code (or point `TOKEN_FINOPS_ENERGY_JSON` at
your own copy).

### 1. ~600 Wh per 1M tokens, accelerator-side — **estimate, low confidence**

No cloud AI provider — Anthropic, OpenAI, Google, AWS — publishes energy per token. What
does exist is a handful of published **per-query** figures, which have to be divided by an
assumed response length to become per-token:

| Source | Figure | Output tokens/query | Per 1M tok | Note |
|---|---|---|---|---|
| **Epoch AI**, *How much energy does ChatGPT use?* (7 Feb 2025) — [link](https://epoch.ai/gradient-updates/how-much-energy-does-chatgpt-use) | ~**0.3 Wh**/query (GPT-4o) | **500, stated** | **600 Wh** | ← **used here.** Bottom-up model: 200B-param MoE (100B active), H100s, 10% utilisation. The only source that publishes the denominator needed to divide honestly. |
| **Google**, *Measuring the environmental impact of delivering AI at Google Scale* (21 Aug 2025) — [arXiv:2508.15734](https://arxiv.org/abs/2508.15734) | **0.24 Wh**, 0.03 gCO2e, 0.26 mL water (median Gemini Apps text prompt, May 2025) | **not disclosed** | *underivable* | The only **production-measured** figure in this whole table — and unusable per-token, because the paper publishes no token counts. |
| **Jegham et al.**, *How Hungry is AI?* — [arXiv:2505.09598](https://arxiv.org/abs/2505.09598) | 0.423 ± 0.085 Wh/query (GPT-4o, short) | 300, stated | ~1,410 Wh | 2.4x the figure used here. Defines its prompt classes explicitly. o3: 1.177 Wh. Cite the version — the headline moved 0.43→0.42 between v1 and v6. |
| **Luccioni et al.**, *Power Hungry Processing* (FAccT '24) — [arXiv:2311.16863](https://arxiv.org/abs/2311.16863) | 0.047 kWh / 1000 inferences (text generation) | **10** | ~4,700 Wh | ~8x higher. A100s, no production batching, 10-token outputs. Widely quoted *without* that 10-token caveat. Not a proxy for frontier serving. |
| **de Vries**, *The growing energy footprint of AI*, Joule (2023) — [DOI](https://doi.org/10.1016/j.joule.2023.09.004) | "at most 2.9 Wh" per ChatGPT request | n/a | — | The number everyone quotes. A *Commentary*, not peer-reviewed research; top-down, GPT-3.5-era. The IEA's *Electricity 2024* repeats it **citing de Vries**, so "the IEA says 2.9 Wh" is the same estimate laundered through a second citation, not corroboration. |
| **IEA**, *Energy and AI* (Apr 2025) — [link](https://www.iea.org/reports/energy-and-ai) | ~0.3 Wh small text model; ~5 Wh Llama 3.3 70B; ~115 Wh video gen | n/a | — | GPU-only: excludes PUE, CPU and idle. Useful as a sanity check on magnitude, not directly comparable. |

**The figure used is 600 Wh per 1M output tokens**, taken straight from Epoch AI: 0.3 Wh
per query ÷ **the 500 output tokens per query that Epoch itself assumes**. Using a source's
own stated denominator is the only way to divide a per-query figure honestly, which is why
Epoch anchors this rather than Google's number.

Every step is still soft:

- **the response length is an assumption**, even when it is the source's own. A 200-token
  answer and a 2,000-token answer cost very different amounts for the same "query". Epoch
  notes the *observed* mean is 261 tokens, not 500 — using that would roughly double the
  per-token figure.
- **Jegham et al. is 2.4x higher.** Its GPT-4o short-prompt measurement (0.423 Wh / 300
  output tokens) works out to ~1,410 Wh per 1M tokens. The defensible range is therefore
  **600–1,500 Wh/1M**, and this tool uses the bottom of it. If anything the cloud side is
  flattered.
- **reasoning models are far worse.** Jegham puts o3 at ~2.8x GPT-4o per query, and a
  poorly-batched self-hosted DeepSeek-R1 at ~45x. None of that is modelled.
- **decode dominates, prefill is cheap.** These are really per-*output*-token figures.
  `savings` compares against a blended input+output count, so the cloud side is again
  conservative.
- **model size is unknown.** Haiku-class and Opus-class tokens do not cost the same, and
  no provider breaks this out.
- **Luccioni et al. is not usable here** despite being the most-cited paper in this space:
  its "0.047 kWh per 1000 inferences" for text generation is measured at **10 output
  tokens per inference** on A100s without production batching, which works out to ~4,700
  Wh/1M — nearly 8x the figure used here, and not representative of frontier production
  serving. It is widely quoted without that caveat.
- **the 2.9 Wh/query number you have seen everywhere is stale and circular.** It comes
  from de Vries (Joule, 2023) — a *Commentary*, not peer-reviewed research, using a
  top-down 2023 SemiAnalysis estimate of GPT-3.5-era serving. The IEA's *Electricity 2024*
  repeats it citing de Vries, so "the IEA says 2.9 Wh" is not independent corroboration;
  it is the same 2023 estimate laundered through a second citation.

This is why the output prints a `Confidence: LOW` line, and why the number is deliberately
round (600, not 587).

### 2. PUE 1.13 — **well-sourced, medium confidence**

Power Usage Effectiveness: total facility power divided by IT power, i.e. the cooling and
distribution overhead on top of the chips. The three largest cloud providers publish
fleet-wide figures:

| provider | PUE | period | source |
|---|---|---|---|
| Google | **1.09** | CY2025 trailing twelve months | <https://datacenters.google/efficiency/> |
| AWS | **1.14** | CY2025 global | <https://sustainability.aboutamazon.com/products-services/aws-cloud> |
| Microsoft | **1.17** | FY25 (Jul 2024–Jun 2025) | <https://datacenters.microsoft.com/sustainability/efficiency/> |

**1.13** is the midpoint. Two things worth knowing: the widely-quoted Microsoft figure of
1.18 is **stale** — that is their first-ever 2022 disclosure, not a current number. And the
industry-wide average is far worse than any of these (Uptime Institute's 2026 survey puts
it at 1.52), but hyperscale AI serving does not run in an average facility, so the
hyperscale figures are the right ones here.

This is the least uncertain input; the spread between providers barely moves the result.
All three exclude or obscure leased colocation capacity, and the reporting periods are not
like-for-like. Note also that Google's 0.24 Wh figure already includes overhead, so
applying PUE on top of a Google-derived number would double-count — another reason the
energy input is anchored on Epoch's accelerator-side estimate instead.

### 3. Grid carbon intensity — **well-sourced, and it overturns the premise**

`--cloud-region` picks which grid the cloud tokens are assumed to burn on:

| key | gCO2/kWh | what it is |
|---|---|---|
| `us-avg` (default) | **350** | US national average. EPA **eGRID2023 rev2** (published 12 Jun 2025, data year 2023): CO2e total output rate 770.884 lb/MWh = 349.7 g/kWh — [summary tables](https://www.epa.gov/system/files/documents/2025-06/summary_tables_rev2.pdf). EIA's Electricity Profile for data year 2024 gives 785 lb/MWh = 356 g/kWh. eGRID2024 had not been released as of Sept 2026. |
| `us-virginia` | **270** | Northern Virginia, "Data Center Alley" — eGRID subregion SRVC. EIA's [Virginia state profile](https://www.eia.gov/electricity/state/virginia/) (2024) gives 286 g/kWh. **~20–30% cleaner than the national average**, driven by ~28–40% nuclear and only ~1.9% coal. |
| `us-ercot` | **334** | Texas / ERCOT — eGRID subregion ERCT. EIA's [Texas state profile](https://www.eia.gov/electricity/state/texas/) (2024) gives 373 g/kWh. Gas supplies ~50% of generation, but wind+solar supply ~28.5%. |
| `de-grid` | **344** | German grid mix, so you can compare cloud vs. local hardware **on the same grid** and isolate the hardware-efficiency difference from the grid-mix difference. Source below. |

**This is the part of the research that changed the answer.** The task that produced this
feature was framed around showing "German/European power mix vs. the US AI Industry (gas,
etc.)" — the intuition being that US AI datacentres run on gas and are therefore dirty.
The published grid data does not support that:

- **Northern Virginia, the densest concentration of AI datacentres on earth, is roughly
  20–30% cleaner than the US average**, because Dominion's mix is heavily nuclear and
  almost coal-free.
- **ERCOT, the genuinely gas-heavy case, still lands at or slightly below the US
  average**, because Texas wind and solar supply more than a quarter of it.
- Germany at 344 g/kWh is now *within noise* of the US national average at 350, having
  decarbonised sharply (379 in 2023 → 353 in 2024 → 344 in 2025).

So there is no "dirty American gas vs. clean European grid" story to tell here, and the
tool does not tell one. There is no `us-gas-heavy` region key, because inventing a 450
g/kWh "representative gas-heavy datacentre grid" — which is what an earlier draft of this
file did — would have been asserting a conclusion the data contradicts.

One real caveat on Virginia: it **imports ~30% of the electricity it consumes** from the
dirtier western PJM pool (eGRID subregion RFCW, ~416 g/kWh). The 270 figure is
generation-based; a consumption-based figure would be materially higher. Consumption-based
lifecycle providers such as Electricity Maps typically run 20–50% above eGRID's
combustion-only generation-based rates, so **do not compare figures across those two
conventions**.

#### Local-side tariff figures, re-sourced

Both grid figures behind the `--power` tariffs were updated by this work:

| tariff | was | now | source |
|---|---|---|---|
| `grid-de-household` | 380 | **344** | Umweltbundesamt **CC 16/2026**, published Mar 2026 — [PDF](https://www.umweltbundesamt.de/system/files/medien/11850/publikationen/2026-03/16_2026_CC.pdf). Series: 2023 final 379, 2024 preliminary 353, 2025 estimate 344. The old 380 was the 2023 figure in its *first* published vintage, since revised to 379. Preliminary vintages move by up to ~10 g. |
| `grid-us-avg` | 390 | **350** | EPA eGRID2023 rev2, as above. The old 390 was an unsourced round number. |
| `solar-de-*` | 40 | 40 | unchanged — lifecycle emissions for rooftop PV. |

**A convention mismatch worth knowing about**: the grid figures use the *direct combustion*
convention (what national inventories publish), while the PV figures are *lifecycle* (there
is no combustion to measure for a solar panel). That mismatch slightly understates the grid
side. The lifecycle-consistent German figure is **406 gCO2eq/kWh**, not 344; Electricity
Maps' consumption-based figure for Germany in 2025 is 335 gCO2eq/kWh. If you want a strict
apples-to-apples solar-vs-grid comparison, use 406 against 40.

## What the numbers are NOT

- **Not embodied carbon.** Neither side counts manufacturing. A MacBook Pro's embodied
  emissions are on the order of a few hundred kg CO2e — for a lightly-used box that can
  dwarf its operational emissions over three years, and it is entirely absent from both
  columns. The output says `energy only` on the header line for exactly this reason.
- **Not water.** Datacentre water consumption is a real and separate impact, not modelled.
- **Not a claim about any specific provider.** Nothing here is an Anthropic, OpenAI,
  Google or AWS figure. Do not quote it as one.
- **Not a licence to greenwash either direction.** On the default settings a desktop Mac
  Studio on the German grid emits roughly **1.4x** the cloud estimate per token, because a
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
