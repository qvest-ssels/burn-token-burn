# 05 — Governance

The retail client from chapter 00 had one governance mechanism: a hard cutoff at the end of the monthly credit pool, with no warning before it hit. That's the worst version of governance, because it fails exactly when it matters most — silently, for everyone at once, with no time to react. Good governance for token spend looks almost nothing like that, and none of it requires taking usage away from anyone in advance.

## Soft limits with alerts, not hard cutoffs

A hard cutoff turns a budgeting problem into an outage. The fix is cheap: alert at a warning threshold (75% of the window used) and a critical threshold (90%), and let people see the warning before they hit the wall instead of after. `token-finops`'s runway model does exactly this — it tracks `used_fraction` against `time_fraction` (a pace ratio: are you burning faster or slower than the clock is ticking?) and reports OK, WARN, or CRITICAL well before EXHAUSTED. Nobody should discover their budget is gone from a failed request; they should have seen it coming for a day.

## Per-team budgets, not one shared pot

A single organisation-wide credit pool has the same failure mode as the retail incident: one team's overnight agent loop takes down everyone else's afternoon. Splitting budgets per team (or, where the provider's plan allows it, per individual) means one team's burst affects its own runway, not a colleague's in a different department who had nothing to do with it. This is more bookkeeping up front and considerably less firefighting later.

## Individual visibility is self-interest, not surveillance

The instinct to resist per-developer usage tracking is understandable — it can read as monitoring people. But the actual case for it is the opposite of punitive: if you can see your own burn rate against your own reset clock, you catch your own runaway loop before it costs you an afternoon, the same way a fuel gauge isn't there to judge your driving. The alternative — no individual visibility, only an aggregate number someone else watches — is what turned the Toom-style incident into three lost weeks instead of a five-minute fix. Visibility that serves the person generating the usage, not just the person auditing it afterward, is the version worth building.

## Runway: the number that actually matters

Everything above collapses into one metric worth watching: runway, the ratio of burn rate to time-in-window, per binding constraint. "Binding constraint" matters because most people run multiple tools with different budget units — Copilot credits, an Anthropic percentage window, a Gemini daily request cap — and those units can't be summed. The right answer isn't a blended dollar figure; it's whichever tool's runway runs out first. A report that shows four tools each at "OK" but doesn't say which one is closest to WARN is not useful. This repo's `report` command exists to answer exactly that question in one line.

## The status-line collector

Anthropic's subscription plans expose usage only as a percentage, and only through the status line — there's no API endpoint a normal user can poll on demand. Wiring `token-finops collect-statusline` as the status-line command means every redraw of the terminal silently stores a usage snapshot; two snapshots inside the same rolling window are enough to compute a burn rate and a real runway estimate, without needing anything beyond what the provider already surfaces:

```jsonc
// ~/.claude/settings.json
{ "statusLine": { "type": "command", "command": "token-finops collect-statusline" } }
```

## The maxing multiplier as a team metric

`token-finops burn --plan <id>` prices a person's or team's actual usage at pay-per-token list
rates and divides by what the seat costs, giving a single number per person: how many times over
they'd have paid the seat's fee on the API. As a team-level signal this is more honest than
"who's using the most tokens", because it's normalised against what the org is already paying —
a Max 20x seat sitting under 1x is money left on the table (the person would be cheaper on a
smaller plan, or is barely using the tool at all); the same seat over 3x is a power user getting
real value out of it. Neither reading is a judgement of the person's work: it says whether the
plan shape fits the usage, not whether the usage was good. Use it to right-size seats, not to
rank people. `burn --by month --history` (recording history from the same refresh timer as
`status --fresh`) turns this into a monthly review: one table per team or per person, maxing
multiplier per month, without waiting for a live tool's own retention window to still hold the
data.

## Checklist

- Set warning and critical alert thresholds (75% / 90%) — never a silent hard cutoff.
- Split budgets per team; don't pool spend across groups that don't affect each other's work.
- Give individuals their own runway view — it's a fuel gauge, not a report card.
- Track the binding constraint, not a blended dollar total across incompatible units.
- Wire the status-line collector for any tool (like Claude Code) that only exposes usage as a percentage.
- Re-run `self-audit` after any workflow change and compare model-cost share before and after.

## Contributing an adapter

If your team uses a coding agent this repo doesn't cover yet, an adapter is a `ProviderAdapter` with two methods: `.scan()` returning an iterable of `UsageEvent`s, and `.quota()` returning a `QuotaSnapshot` or `None` when the provider doesn't expose one. Look at an existing adapter under `src/token_finops/adapters/` for the shape, add a synthetic fixture under `tests/`, and send a PR — the field-source table in `docs/ADAPTERS.md` documents what's verified against source versus reverse-engineered, so a new adapter should extend that table honestly rather than guess at an undocumented field.
