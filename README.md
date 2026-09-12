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
| OpenCode / Kilo CLI | `~/.local/share/{opencode,kilo}/*.db` | BYO provider ($) | usage ✓ |
| Cline / Roo / Kilo (VS Code) | `…/globalStorage/<ext>/tasks/*/ui_messages.json` | BYO provider ($) | usage ✓ |
| Aider | `.aider.chat.history.md`, opt-in analytics JSONL | BYO provider ($) | usage ✓ (timestamps approximate) |
| Continue.dev | `~/.continue/sessions/*.json` | BYO provider ($) | usage ✓ (low confidence) |
| Cursor · Windsurf · Ollama | — | see `docs/adr/0008`, `0011`, `0012` | reference-only |

Usage-only tools get a runway too when you pass `--allowance <USD per 30 days>`.

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
uv venv && uv pip install -e "token-finops-cli[dev]"   # the package lives in token-finops-cli/
uv run token-finops adapters                            # which data sources were found on this machine
uv run token-finops report  # per-tool usage (7d) + runway
token-finops report --tool copilot --budget 1500      # your plan's monthly credits
token-finops sessions --tool claude_code --since 30d
token-finops self-audit     # what did the last Claude Code session cost, incl. sub-agents
token-finops burn --plan claude:max-20x --efficiency  # are you maxing your plan?
```

No real telemetry on hand? Generate a throwaway one — a complete synthetic
fake-home tree for all nine adapters, nothing real ever touched:

```bash
eval "$(token-finops synth --out /tmp/demo-home --print-env)" && token-finops report --compact
```

See [`docs/SYNTH.md`](docs/SYNTH.md) for burn-profile scenarios (`burst`, `exhausted`, `weekend`, ...).

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

## Are you maxing your plan?

Subscriptions never publish a token allowance, so a flat fee can't be turned into "$ per
token" directly — but it can be compared the other way round: price the same calls at
pay-per-token list prices and divide by what the plan costs. `token-finops burn` does exactly
that, plus a weekly/monthly token report and a burn-efficiency breakdown (cache hit rate,
frontier-model share, sub-agent share, routing dividend).

```
$ token-finops burn --plan claude:max-20x
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
```

See [`docs/BURN.md`](docs/BURN.md) for the maxing multiplier, plan-months, `--by day|week|month`,
recorded history past a tool's own retention, and the full efficiency-metric reference.

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

## Status line / tmux / editors

One renderer for every surface, backed by a cache so widgets never rescan your transcripts:

```bash
token-finops status                       # CC 61% 2h! | CX 17% 3h | CP 29% 41d | binds: CC
token-finops status --format tmux         # colour escapes for status-right
token-finops status --format starship     # binding constraint only
token-finops status --format waybar       # JSON with class/tooltip; also polybar, i3, xbar, json
```

`contrib/` ships a tmux plugin, systemd/launchd refresh timers, and starship/waybar/SwiftBar
recipes — see [`docs/TMUX.md`](docs/TMUX.md). Editors, agent-native `/runway` skills and the
remaining desktop surfaces are designed in [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

## Tested against 50 real-world use cases

775 tests back this tool, including [`docs/USECASES.md`](docs/USECASES.md)
— 50 executable use cases (`UC-01` … `UC-50`) covering every adapter, the
runway engine's edge cases (year rollover, mid-cycle joins, stale
snapshots), the savings/break-even estimator, and multi-tool reports.
Each row names the pytest id, so `pytest -k UC-13` runs exactly that case.

## Documentation

- [`docs/guide/`](docs/guide/) — **The Qvest Digital Guide to Token Burning** (formerly: Token Efficiency)
- [`docs/landscape.md`](docs/landscape.md) — the niche we cover and who else does: local quota/runway trackers per coding agent
- [`docs/adr/`](docs/adr/) — one Architecture Decision Record per coding assistant (support tier, data source, open questions)
- [`docs/ADAPTERS.md`](docs/ADAPTERS.md) — how to add a tool, with verified field tables
- [`docs/PLAN.md`](docs/PLAN.md) — the structured plan and dogfooding record
- [`docs/SYNTH.md`](docs/SYNTH.md) — the synthetic telemetry generator, used for demos and the whole test suite
- [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) — status line / tmux / waybar / editor / desktop integrations (design proposal)
- [`docs/USECASES.md`](docs/USECASES.md) — all 50 executable use cases
- [`docs/BURN.md`](docs/BURN.md) — `burn`: maxing multiplier, weekly/monthly tables, history, burn efficiency
- [`docs/INSTALL.md`](docs/INSTALL.md) — installing token-finops itself, and installing the coding-agent CLIs each adapter reads (macOS/Linux)
- [`docs/README.md`](docs/README.md) — index of everything under `docs/`
- [`AGENTS.md`](AGENTS.md) — rules for coding agents (Claude Code, Codex, Copilot) working in this repo
- [`docs/sources.md`](docs/sources.md) — every price, quota and endpoint with its source and review date
- [`CHANGELOG.md`](CHANGELOG.md) — release history
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, tests/lint, how to add an adapter, PR checklist

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
