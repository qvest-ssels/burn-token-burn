# `token-finops cost-per-token`

$ per 1M tokens, broken down by tool and model. Two different numbers are shown side
by side, and they mean different things:

| Column | What it is |
|---|---|
| `list in/out` | The provider's published pay-per-token API price (`$/Mtok` input/output), from `core/pricing.py`. A real rate, whether or not you actually pay it. |
| `realized` | What you *actually* paid per token this window, blended across input/output/cache at your real mix — for a tool whose adapter already computes `usd_estimate` off the list price (Claude Code, Codex, Gemini CLI, Hermes/OpenRouter, OpenCode, Cline/Roo/Kilo, Aider, Continue.dev). |
| `derived` (marked `*`) | A back-calculated ratio for a tool that does not bill per token at all: its native cost, converted to USD where the conversion is fixed, divided by the tokens observed for that model. Always followed by a legend line. Never a rate the provider publishes. |

A row never carries both `realized` and `derived` — a tool either has a real per-token
price or it doesn't.

## Does this work for GitHub's AI tokens (Copilot)?

No, not as an official rate — and that's worth spelling out rather than papering over.

GitHub Copilot bills in **AI credits / premium requests** (`total_nano_aiu` in
`~/.copilot/session-store.db`; 1 credit = $0.01 — see `adapters/copilot.py`), not in
$/token. The credit cost of a request is set by a **per-model request multiplier**: a
short reply from a frontier model and a long reply from a cheap model can consume the
same number of credits, because the multiplier is per-request, not per-token. GitHub
has never published a $/token or credits/token conversion, so `cost-per-token` for
Copilot can only show the **derived** ratio: credits spent this window, converted to
USD at the fixed $0.01/credit rate, divided by the tokens the adapter happened to
observe for that model. That ratio:

- moves with your model mix (more frontier-model calls at the same credit spend look
  like a *higher* $/token, and vice versa) — it is not a fixed price,
- is a personal reference point for "what am I effectively paying per token, blended",
  not something to compare against another provider's real per-token rate,
- is always rendered with a trailing `*` and a legend explaining exactly this.

Every other supported tool that bills per token at all (i.e. every pay-per-token API
key) gets the real list price and, once you have usage, the `realized` blended rate —
no derivation needed.

## Usage

```
token-finops cost-per-token [--tool copilot|claude_code|...] [--since 1d|7d|30d|90d|365d|all] [--json]
```

```
$ token-finops cost-per-token --tool copilot --since 30d
GitHub Copilot CLI (last 30d) -- $ per 1M tokens
  model                        calls    tokens   list in/out   realized    derived
  gpt-5                           28    471.5k     1.25/10.00        n/a    $587.73*
  claude-sonnet-4-5               28    384.4k     3.00/15.00        n/a    $660.93*
  * derived from AI-credit billing (1 credit = $0.01) divided by observed tokens -- not
    an official per-token price; it drifts with your model mix.
```

(The large numbers above are from the bundled synthetic fixture, whose per-request AIU
scale is intentionally exaggerated for demo purposes — see `claude-tasks.md` T-02. On
a real Copilot account the derived rate lands in a much more modest range.)

`--json` returns, per tool, a list of rows with `calls`, `input`/`output`/`cache_read`/
`cache_write`/`tokens`, `list_price_in`/`list_price_out`, `realized_usd_per_mtok`, and
`derived_usd_per_mtok` (each of the last two `null` when not applicable).

See also [`BURN.md`](BURN.md) — `burn`'s maxing multiplier answers a related but
different question ("is my subscription worth it against the API-equivalent price");
`cost-per-token` answers "what does one million tokens cost, by model, right now."
