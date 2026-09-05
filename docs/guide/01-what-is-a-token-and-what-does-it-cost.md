# 01 — What Is a Token, and What Does It Cost?

A token is roughly three-quarters of a word — the unit a language model actually reads and writes, produced by a tokenizer that splits text (and code, and image descriptions) into sub-word chunks. That part is boring and well documented. What's not boring, and not well documented anywhere a normal developer would look, is what a token *costs you*, because that answer depends entirely on which door you walked through to use the model.

## Three rubber currencies, one real one

If you pay per API token, the price is a number: dollars per million input tokens, a different number per million output tokens, usually a steep discount for cache reads. That's the only currency in this list with a fixed exchange rate. Everything else is a rubber currency — a unit invented by the vendor that expands, contracts, or gets redefined without notice:

- **GitHub Copilot / GitHub AI Credits.** Since June 1, 2026, Copilot usage is metered in "AI Credits" bundled into each plan: Pro at $10/month, Pro+ at $39/month, Business at $19/month, Enterprise at $39/month. A credit is not a token — it's an opaque multiplier that varies by model and request type, set by GitHub, changeable by GitHub.
- **Anthropic Claude plans.** Pro and Max subscriptions expose usage as a percentage of a rolling 5-hour and 7-day window — never a token count, never a dollar figure. The percentage-to-token conversion isn't published and isn't guaranteed to stay the same across model versions.
- **Gemini CLI.** Metered in requests per day (1,000 free, 1,500 or 2,000 on paid tiers), not tokens. A single "request" can be a one-line completion or a 100-file refactor; both count the same against the daily cap.

None of these three units convert cleanly into each other, into tokens, or into dollars — that's the point of a rubber currency: it lets the vendor adjust the real cost of usage (via model routing, quality changes, or quiet re-pricing) without ever changing the sticker number you see.

## The 15–30x you're not supposed to notice

Here's why the rubber currencies matter in practice, not just in principle. Take a heavy subscription user: 440 coding-agent sessions and roughly 18,000 conversational turns in a billing cycle. Priced at pay-per-token API rates for the models actually used, that workload comes out to about **$1,588**. The subscription that covered it costs **$200**. That's a 15–30x gap between what the work would cost on the metered API and what the flat-rate plan charges for it — and it's not a rounding error, it's the entire business model. Subscriptions are underwritten by the assumption that most users don't run 440 sessions a cycle; the ones who do are receiving something between a loss-leader and a genuine subsidy, and the vendor has every incentive to eventually meter, throttle, or reprice that behavior once it becomes common enough to show up in their unit economics.

This is not a complaint — it's a fact to plan around. If your team's workflow looks like the heavy end of that distribution, the plan you're on today is not a stable input to a budget forecast; it's a promotional price that will move.

## Discounts, model updates, and model end-of-life are the same risk

Three things can change your effective token price without you changing anything: a vendor discount expiring, a model version being swapped under a plan's hood (same subscription, different — usually cheaper for them, not necessarily worse for you — model), and a model being deprecated outright. Treat all three the way you'd treat any vendor dependency in a business-continuity plan: know which model IDs you depend on, know the deprecation notice period your vendor actually gives (not the one they advertise), and don't build a workflow whose economics only work because of a price that has an expiry date attached, even an unstated one. The rubber currencies exist precisely so this kind of change can happen quietly. Assume it will.
