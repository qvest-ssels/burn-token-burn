# `token-finops burn` — are you maxing your plan?

Subscriptions (Claude Pro/Max, Copilot Pro/Pro+, ChatGPT Plus/Pro, Google AI Pro/Ultra) never
publish a token allowance. There is no number to divide the flat fee by, so a subscription can
never be turned into an honest "$ per token" rate — Anthropic doesn't say how many tokens a
Pro seat is worth, and neither does anyone else. `burn` compares the other direction instead:
price the same calls at pay-per-token list prices (the API-equivalent `report`/`self-audit`
already compute) and divide by the plan price you actually pay. That ratio is the **maxing
multiplier** — how many times over you would have paid your subscription fee had you bought
the same usage on the API.

```
maxing = API_equivalent_usd_per_30d / plan_usd_per_month
```

Five bands, deliberately blunt:

| multiplier | label |
|---|---|
| < 0.5x | subsidising the provider |
| 0.5–1x | break-even-ish |
| 1–3x | normal heavy use — the plan pays off |
| 3–10x | token maxing |
| ≥ 10x | arson |

None of this changes what you're billed — plans don't meter tokens, so nothing here can trigger
an overage. It's a way to see whether the plan you're on is the right shape for how you actually
use it, and to compare plans against each other on one axis instead of guessing from marketing
tiers ("5x Pro usage" is not a number until you price your own calls).

## Worked example

Real output, Claude Code, last 6.5 days:

```
$ token-finops burn --plan claude:max-20x --efficiency
Burn report: Claude Code (last 30d)
  span: 2026-09-04 -> 2026-09-11  (6.5 days, 5 active)   calls 645   tokens 70.4M
  API-equivalent:      $64.21   (list prices, reviewed 2026-09-11)
  run-rate:           $298.00   per 30 days

Plan equivalents — maxing = API-equivalent per 30 days / plan price:
  plan                          $/month  plan-months   maxing  verdict
  Claude Pro                      20.00          3.2    14.9x  arson
  Claude Max 5x                  100.00          0.6     3.0x  token maxing
  Claude Max 20x                 200.00          0.3     1.5x  normal heavy use  <- yours
  Claude Team (premium seat)     150.00          0.4     2.0x  normal heavy use
  -> on Claude Max 20x you burn 1.5x the fee in API terms: normal heavy use

Burn efficiency:
  cache hit ratio        96.6%   of input-side tokens served from cache
  frontier share         90.6%   of $ on frontier-tier models
  sub-agent share        79.7%   of $ spent by sub-agents
  routing dividend        $31.50   saved vs. everything on the frontier model
```

Reading this: $64.21 of API-equivalent spend over 6.5 days annualises (well, "30-days-ises") to
a $298/month run-rate. Against Claude Pro's $20/month that's 14.9x — arson, but only because
Pro was never the right comparison; this account is on Max 20x, where the same run-rate is 1.5x
the fee — normal heavy use, the plan is earning its keep without being maxed out. `plan-months`
(here 0.3 on Max 20x) says the same thing in a different unit: at this burn rate, 30 days of
usage would have bought 0.3 months of the plan on the API — i.e. the plan is the cheaper option,
by roughly 3x, for this workload. The efficiency block underneath explains *why* the number is
what it is: 96.6% of input-side tokens came from cache (cheap), but 90.6% of the dollars still
went to frontier-tier models and 79.7% to sub-agents — the multiplier is high not because of
wasted tokens but because the mix leans on the most expensive model most of the time.

## Plan-months

`plan-months = API_equivalent_usd_total / plan_usd_month` — the same ratio as maxing but against
total spend in the window rather than the 30-day run-rate, so it doesn't assume the window was a
full month. Useful when `--since` is short (a week, a session) and you want "how many months of
this plan did I burn through", not an extrapolated monthly rate.

## Weekly/monthly tables (`--by day|week|month`)

`--by` adds a per-period table below the plan comparison, aggregated from the same events:

```
$ token-finops burn --by month --tool claude_code --since all
By month:
  period     days  calls   tokens   API-eq $    /30d $
  2026-09       5    646    70.4M      69.18     69.18
```

`days` is the number of days with at least one call in that period (not the calendar length —
`period_days()` in `burn/history.py` supplies the calendar length separately, for the `/30d $`
run-rate normalisation, so a partial month doesn't look artificially cheap). With `--plan` set, a
`maxing` column is appended per period, so a monthly review can see which month actually maxed
the plan rather than only the trailing window average.

`day` and `week` use UTC calendar boundaries; `week` is ISO week (`YYYY-Www`), matching
`datetime.isocalendar()`.

## History: `--history` and `--record`

The live adapters only see what the tool itself still has on disk — Claude Code prunes
transcripts after roughly 30 days, Codex archives old rollouts, Copilot's session-store can be
reset outright. `--by month --since all` run against live data alone is therefore bounded by
whatever the *shortest-memory* tool still remembers, not by anything `token-finops` controls.

`burn/history.py` works around this with a small append-only side file,
`~/.token-finops/history.jsonl` (override: `--history-file`), one line per tool per UTC day:

```json
{"schema_version": 1, "tool": "claude_code", "day": "2026-09-04", "calls": 217, "input": 434,
 "output": 12958, "cache_read": 20887275, "cache_write": 457699, "usd": 26.33,
 "by_model": {"claude-fable-5-1": 26.09, "claude-sonnet-5": 0.23},
 "recorded_at": "2026-09-11T07:05:43+00:00"}
```

- `--record` folds *today's* live view (actually: every day the adapter still has, upserted by
  `(tool, day)`) into that file. Run it from the same timer that refreshes `status --fresh`
  (`contrib/refresh/`) — every couple of minutes is fine, upsert is idempotent and keyed by day,
  so re-recording the same day just overwrites it with a fresher count.
- `--history` merges that file into the current view so `--by` can report on days the live
  adapter has already forgotten. Live data always wins over a recorded day for the same
  `(tool, day)` (`hist.merge_live`) — history only fills gaps, never overrides what's still
  directly observable.
- Both are independent of `--since`, which still bounds the final window — combine `--history`
  with `--since all` or `--since 365d` or it will look back no further than the live window did.

Without ever running `--record`, `--history` is a no-op (nothing to merge in) and `--by` only
covers what the tool's own retention still holds.

## `--efficiency` / `--nerdy`

Everything in the maxing multiplier is one number; `--efficiency` (alias `--nerdy`) unpacks *why*
it's that number, as ratios of quantities observed locally — no provider-side telemetry beyond
what `report`/`self-audit` already read.

| metric | formula | caveat |
|---|---|---|
| cache hit ratio | `cache_read / (input + cache_read + cache_write)` | share of *input-side* tokens, not all tokens; output is never cached |
| cache saved | `no_cache_price - actual_price`, where `no_cache_price` reprices the same call with every cached token billed as fresh input | counterfactual: assumes the same call would have been made identically without caching, which is optimistic — without caching you might have sent less context per call |
| output share | `output_tokens / total_tokens` | typically tiny (well under 1%) in agentic sessions; most tokens are re-sent context, not new writing |
| $ per 1k output | `usd / output_tokens * 1000` | prices "a thousand tokens of actual answer", context and all — not comparable to a raw per-token model price |
| tokens per call | `total_tokens / calls` | context dragged along per request; large numbers mean big system prompts / long histories, not necessarily waste |
| frontier share | fraction of `$` spent on models whose *list output price* is ≥ $20/Mtok | "frontier" is a price-based cutoff (`TIER_BOUNDS` in `burn/__init__.py`), not a claim about model capability — a provider could reprice a model across the line without changing what it does |
| sub-agent share | fraction of `$` on events carrying an `agent_id` | depends on the adapter correctly tagging sub-agent calls (Claude Code, Gemini CLI); tools that don't distinguish sub-agents report `n/a`-equivalent (0 subagents) |
| routing dividend | `(cost if every call had run on the most expensive model in the mix) - (actual cost)` | counterfactual, and only as good as "the most expensive model already in the mix" — it does not know about an even pricier model you never called, and it says nothing about whether the actual routing chose correctly per call, only the aggregate saved-vs-worst-case |

The example above: cache hit 96.6% (most input-side tokens were cheap re-sends), frontier share
90.6% (nine dollars in ten went to the frontier-tier model), sub-agent share 79.7% (most of that
frontier spend was sub-agents, not the main loop), routing dividend $31.50 (still, mixing in
cheaper models where they were used saved about a third of what "everything on the frontier
model" would have cost). None of the three headline shares are inherently good or bad — a
sub-agent-heavy, frontier-heavy session might be exactly the right call for a hard research task,
and the same numbers on a routine edit would be a signal to look at model routing.

## `--rate IN/OUT[/CR[/CW]]` — prepaid / committed-spend rate

Some organisations negotiate a flat per-token rate with a provider (committed spend, enterprise
contract) instead of paying list price per call. `--rate` reprices the whole window at one flat
rate in $ per million tokens: `IN/OUT` (e.g. `3/15`) or `IN/OUT/CACHE_READ/CACHE_WRITE` (e.g.
`3/15/0.3/3.75`). Missing cache rates default to Anthropic's own list-price ratios — 10% of the
input rate for a cache read, 125% for a cache write — since most negotiated rates keep those
ratios even when the base rate changes:

```
$ token-finops burn --rate 3/15
  prepaid rate:    $30.50   at $3/15 in/out, $0.3/3.75 cache r/w per Mtok (44% of list)
```

This does not touch the plan-equivalent table — a prepaid API rate and a subscription plan are
two different ways to pay, and `--rate` only answers "what would this window cost under that
contract", not "should I be on a plan instead".

## `--discount FRACTION` — promo pricing

`--discount 0.5` shows list price times `(1 - 0.5)` alongside the real API-equivalent, for a flat
promotional or negotiated discount off list (not a per-model rate like `--rate`, just a multiplier
on the total). Must be in `[0, 1)`; `1.0` or higher is rejected since "free" isn't a discount on a
price, it's a different number.

## Plan catalogue and overrides

The bundled catalogue (`token-finops-cli/src/token_finops_cli/burn/plans.json`) is a monthly-list-
price snapshot with a `review_date` and a `sources` list, printed at the top of `burn --plans`:

```
Plan catalogue (reviewed 2026-09-11; override ~/.token-finops/plans.json):
  claude:pro           Claude Pro                   $  20.00/mo   5h/7d rolling windows; ...
  claude:max-20x       Claude Max 20x                $ 200.00/mo   20x Pro usage
  ...
```

Prices drift and this file will go stale between reviews. Override or extend it with
`~/.token-finops/plans.json` — same shape (`{"plans": [{"id", "tool", "name", "usd_month", ...}]}`),
merged into the bundled catalogue by `id` (your entry wins field-by-field, so you can override
just `usd_month` on an existing plan). Use this for a negotiated enterprise seat price, a plan not
yet in the catalogue, or to correct a price that changed since `review_date`.

See also: [`README.md`](../README.md) for the quick-start, [`docs/guide/02-where-does-the-money-go.md`](guide/02-where-does-the-money-go.md)
for the narrative version of the efficiency metrics against a real session, and
[`docs/guide/05-governance.md`](guide/05-governance.md) for using the maxing multiplier as a team-level metric.
