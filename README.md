# token-finops

**Read-only, local-first token usage and budget-runway tracker for AI coding agents — plus an honest local-vs-cloud savings estimator.**

> "Somebody burned the whole team's Copilot budget. Nobody could send a request for the rest of the month. (It wasn't me — but I couldn't have proven it.)"

`token-finops` grew out of [`token-finops-cli`](https://github.com/oh-my-agent-code/token-finops-cli), a 600-line stdlib script that reads GitHub Copilot CLI's local telemetry and answers one question: *at my current burn rate, does my monthly budget last until the reset?* This repository generalises that "runway" idea to every coding agent that leaves telemetry on your disk, and adds the question people ask next: *would a Mac Studio in the corner be cheaper?*

Everything is Python ≥ 3.10, **standard library only**, and never writes to any tool's own data store.

## What it does

| Tool | Local data source | Budget unit the provider actually enforces | Status |
|---|---|---|---|
| GitHub Copilot CLI | `~/.copilot/session-store.db` | AI credits / month (resets 00:00 UTC on the 1st) | port of the original, extended |
| Claude Code | `~/.claude/projects/**.jsonl` incl. sub-agent transcripts | opaque % of a rolling 5 h and 7 d window | usage ✓, quota via status-line hook |
| OpenAI Codex CLI | `~/.codex/sessions/**/rollout-*.jsonl` | % of rolling 5 h / 7 d window — **written to disk by Codex itself** | usage ✓, quota ✓ offline |
| Gemini CLI | `~/.gemini/tmp/*/chats/*.jsonl` | requests / day (1000 free, 1500/2000 paid) | usage ✓, daily request runway |
| Hermes Agent | `~/.hermes/state.db` | provider-dependent (OpenRouter $, local = none) | usage ✓, local models flagged |

Heterogeneous units are **never summed**. Each tool gets its own runway; the report tells you which one is the *binding constraint* — the one that runs out first.

```
$ token-finops report --compact
GitHub Copilot CLI [######--------------]  29.4%  runway  41.2d  OK
Claude Code        [############--------]  61.0%  runway   1.9h  WARN
OpenAI Codex CLI   [###-----------------]  17.0%  runway   3.4h  OK
Gemini CLI         [#-------------------]   6.1%  runway    inf  OK

binding constraint: Claude Code (5h) — runway 1.9h -> WARN
```

## Quick start

```bash
pip install -e .            # or: pipx install .
token-finops adapters       # which data sources were found on this machine
token-finops report         # per-tool usage (7d) + runway
token-finops report --tool copilot --budget 1500      # your plan's monthly credits
token-finops sessions --tool claude_code --since 30d
token-finops self-audit     # what did the last Claude Code session cost, incl. sub-agents
```

### Claude Code: get the real quota

Anthropic subscriptions expose only a percentage, and only through the status line. Wire the collector as your status line and every redraw stores a snapshot; two snapshots in the same window are enough for a burn estimate:

```jsonc
// ~/.claude/settings.json
{ "statusLine": { "type": "command", "command": "token-finops collect-statusline" } }
```

```
Claude Code — window: 5h (resets 2026-09-05 12:29 UTC)
  budget:   [############------------------]  40.0%
  window:   [############------------------]  40.0% elapsed
  pace:     1.00 (on pace)
  burn:     20.0% per hour (from snapshots)
  runway:   3.0h vs 3.0h left -> OK
```

### Self-audit: what did that session cost?

Claude Code writes one line per content block, so naive counting over-reports by ~1.9x. `self-audit` deduplicates on `(message.id, requestId)`, includes the sub-agent transcripts, and groups by model — because the model, not the token count, decides the bill.

```
Self-audit: Claude Code session 0bbc8283-…
  API calls (deduplicated): 428  = main loop 211 + sub-agents 217
  total tokens:     73.1M     (95 % of them cache reads)
  API-equivalent:   $87.28

By model:
  claude-fable-5-1      255 calls   $73.25   84%
  claude-sonnet-5       172 calls   $14.03   16%

Sub-agents = 30 % of API-equivalent cost
```

That session is the one that built this repository. The three research sub-agents that ran on the frontier model cost more than all the Sonnet work combined — see the [guide](docs/guide/) for what we changed after seeing that.

### Local vs cloud

```
$ token-finops savings --hardware mac-studio-m4-max-128gb --model qwen3-32b --utilization 0.2
  local total:       $8.86 / 1M tok    (capex-dominated at 20 % utilisation)
  cloud (sonnet):    $3.20 / 1M tok    -> CLOUD CHEAPER
  break-even utilisation: 60 % of 24/7

$ token-finops savings --power solar-de-feed-in --utilization 0.8
  local total:       $2.20 / 1M tok    -> LOCAL CHEAPER (0.69x)

$ token-finops break-even --hardware mac-studio-m4-max-128gb
  replaceable cloud usage (haiku/sonnet-class): 35.5M tokens = $14.94 API-equivalent
  local alternative: energy $14.29 + capex $116.87 = $131.15
  -> cloud still cheaper by $116.21; at the current pace the box never pays off
```

Solar is priced at the feed-in tariff you forgo (7.7 ct/kWh in Germany), not at zero. Capex is amortised per hour of *actual* inference. Only Haiku/Sonnet-class work counts as replaceable — a 32B model does not do Opus/Fable-class work. All hardware numbers live in editable JSON with their sources and a review date; measure your own with `powermetrics` / `nvidia-smi` and overwrite them.

## Documentation

- [`docs/guide/`](docs/guide/) — **The Qvest Digital Guide to Token Burning** (formerly: Token Efficiency)
- [`docs/landscape.md`](docs/landscape.md) — the niche we cover and who else does: local quota/runway trackers per coding agent
- [`docs/ADAPTERS.md`](docs/ADAPTERS.md) — how to add a tool, with verified field tables
- [`docs/sources.md`](docs/sources.md) — every price, quota and endpoint with its source and review date

## Design rules

1. **Read-only.** SQLite is opened with `immutable=1`; no locks, no WAL interaction with the live app.
2. **Fractions, not dollars.** Budgets are normalised to "fraction of the window used". USD appears only as a labelled *API-equivalent* estimate.
3. **Provider percentage beats local sums** when the provider gives one (Codex writes it to disk; Claude Code pushes it through the status line).
4. **Pessimistic burn.** Runway uses the larger of cycle-average and 7-day EMA burn, so yesterday's burst shows up today.
5. **Schema drift is expected.** Adapters use field aliases, skip bad lines, and ship synthetic fixtures.

## Related

This is *not* another awesome-list. Two good ones exist — send tracker PRs there:
[QuesmaOrg/awesome-ai-tokenomics](https://github.com/QuesmaOrg/awesome-ai-tokenomics) ·
[pleasedodisturb/awesome-llm-token-optimization](https://github.com/pleasedodisturb/awesome-llm-token-optimization).
Tools that overlap with ours and that we happily point to: [ccusage](https://github.com/ryoppippi/ccusage), [Claude Code Usage Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor), [OpenTokenMonitor](https://github.com/Hitheshkaranth/OpenTokenMonitor), [cc-statistics](https://github.com/androidZzT/cc-statistics), [tokscale](https://github.com/junhoyeo/tokscale).

## License

AGPL-3.0-or-later, like the original. © Qvest Digital and contributors.
