# token-finops-cli

Read-only, local-first token usage and budget-runway tracker for AI coding
agents. **v0.3.0** grew this out of the original 0.2.x line — a single
600-line script that read GitHub Copilot CLI's local telemetry — into a
modular tool with **9 adapters** (Copilot, Claude Code, Codex CLI, Gemini
CLI, Hermes Agent, OpenCode/Kilo, Cline/Roo/Kilo, Aider, Continue.dev), a
shared runway engine, a self-audit for Claude Code sessions, and a
local-vs-cloud savings estimator. The philosophy hasn't changed: standard
library only, no runtime dependencies, and it never writes to any tool's
own data store — SQLite is opened read-only/immutable where applicable.

Everything below that talks about the original Copilot budget/cycle/session
reports still works exactly as it did in 0.2.x.

## Install

```bash
uv tool install token-finops-cli          # recommended
pipx install token-finops-cli
pip install token-finops-cli
```

## 60-second tour

```bash
$ token-finops adapters
  tool         found  root
  copilot      yes    ~/.copilot
  claude_code  yes    ~/.claude
  codex        no     ~/.codex
  gemini_cli   no     ~/.gemini
  hermes       no     ~/.hermes
  opencode     no     ~/.local/share/opencode
  cline        no     ~/.config/Code/User/globalStorage
  aider        no     ~
  continue     no     ~/.continue
```

Empty output? `doctor` says why, per tool, and what to do about it:

```bash
$ token-finops doctor
token-finops doctor — what `report` can and cannot see on this machine

  token-finops-cli 0.3.0
  Python 3.12.7 (/usr/local/bin/python3)
  platform Darwin 24.5.0

  [found]   Claude Code (claude_code) — 13305 events, latest 2026-09-14 20:14 UTC
      probed: ~/.claude/projects  (exists)
      hint:   5h/7d quota percentages only exist in the status line: wire
              `token-finops collect-statusline` as statusLine.command in ~/.claude/settings.json.

  [empty]   OpenAI Codex CLI (codex)
      probed: ~/.codex  (exists)
      hint:   Codex CLI's home exists but has no rollout-*.jsonl sessions — run `codex` once.

  [missing] Gemini CLI (gemini_cli)
      probed: ~/.gemini  (not found)
      hint:   No ~/.gemini. Install the Gemini CLI (`brew install gemini-cli` or
              `npm install -g @google/gemini-cli`), or set GEMINI_CLI_HOME.
  ...

  summary: 1 with data, 1 installed but no usage yet, 7 not found
```

`found` = the adapter read usage events; `empty` = the tool's data location
exists but holds no usage yet; `missing` = the coding agent itself does not
look installed (or its data lives somewhere else — every entry names the
environment variable that repoints it). `doctor` always exits 0: an empty
machine is a normal state, not a failure. `--tool` narrows it to one adapter.

```bash
$ token-finops report --compact
GitHub Copilot CLI [######--------------]  29.4%  runway  41.2d  OK
Claude Code        [############--------]  61.0%  runway   1.9h  WARN

binding constraint: Claude Code (5h) — runway 1.9h -> WARN
```

```bash
$ token-finops sessions --tool claude_code --since 30d
Claude Code sessions (last 30d):
  session_id      started              calls   tokens   API-eq $
  0bbc8283-…      2026-09-05 09:12     428     73.1M    87.28
  …
```

```bash
$ token-finops self-audit
Self-audit: Claude Code session 0bbc8283-…
  API calls (deduplicated): 428  = main loop 211 + sub-agents 217
  total tokens:     73.1M     (95 % of them cache reads)
  API-equivalent:   $87.28

By model:
  claude-fable-5-1      255 calls   $73.25   84%
  claude-sonnet-5       172 calls   $14.03   16%

Sub-agents = 30 % of API-equivalent cost
```

```bash
$ token-finops savings --hardware mac-studio-m4-max-128gb --model qwen3-32b --utilization 0.2
  local total:       $8.86 / 1M tok    (capex-dominated at 20 % utilisation)
  cloud (sonnet):    $3.20 / 1M tok    -> CLOUD CHEAPER
  break-even utilisation: 60 % of 24/7
```

```bash
$ token-finops break-even --hardware mac-studio-m4-max-128gb
  replaceable cloud usage (haiku/sonnet-class): 35.5M tokens = $14.94 API-equivalent
  local alternative: energy $14.29 + capex $116.87 = $131.15
  -> cloud still cheaper by $116.21; at the current pace the box never pays off
```

```bash
$ token-finops synth --out /tmp/demo-home --print-env && \
  eval "$(token-finops synth --out /tmp/demo-home --print-env)" && \
  token-finops report --compact
```

runs the whole CLI against a fully synthetic, throwaway fake-home tree — no
real telemetry anywhere. See `docs/SYNTH.md` in the repo root for scenarios
(`steady`, `burst`, `exhausted`, `weekend`, `fresh`, `quiet`,
`subagent-heavy`).

## GitHub Copilot CLI (the original tool)

`token-finops-cli` still reads `~/.copilot/session-store.db`
(`assistant_usage_events`) directly — no external API calls, nothing
leaves your machine, the DB is opened read-only. (The one exception is
opt-in and never on by default: `--online`, below.)

```bash
token-finops report --tool copilot                  # 7-day summary + runway (default window)
token-finops report --tool copilot --budget 1500 --cycle-day 1   # your plan's monthly AI units
token-finops report --tool copilot --compact        # 2-line minimal output
token-finops report --tool copilot --watch 5        # live-refreshing view every 5s
```

Session history and break/gap reports (per-session archival view, distinct
from the runway report):

```bash
token-finops sessions                       # list all past Copilot sessions
token-finops sessions --since 30d --limit 10
token-finops sessions --session <id>                    # detailed break/gap report
token-finops sessions --session <id> --gap-minutes 60
token-finops sessions --totals              # ONE combined report across ALL sessions
```

The detailed per-session view reports "breaks" — gaps between requests
longer than `--gap-minutes` (default 30) — and active vs. idle wall-clock
time. The "AI unit" is GitHub's own cost/usage unit (`total_nano_aiu / 1e9`)
— the same number shown on the Copilot billing page, not raw token counts.

## Claude Code: status-line hook

Anthropic subscriptions expose only a percentage of a rolling 5h/7d window,
and only through the status line. Wire the collector as your status line
command; every redraw stores a snapshot, and two snapshots in the same
window are enough for a burn estimate:

```jsonc
// ~/.claude/settings.json
{ "statusLine": { "type": "command", "command": "token-finops collect-statusline" } }
```

```bash
token-finops report --tool claude_code --json
```

```
Claude Code — window: 5h (resets 2026-09-05 12:29 UTC)
  budget:   [############------------------]  40.0%
  window:   [############------------------]  40.0% elapsed
  pace:     1.00 (on pace)
  burn:     20.0% per hour (from snapshots)
  runway:   3.0h vs 3.0h left -> OK
```

## Status bars: tmux, starship, waybar, SwiftBar

```bash
token-finops status                      # CC 61% 2h! | CX 17% 3h | CP 29% 41d | binds: CC
token-finops status --format tmux        # for status-right (contrib/tmux/token-finops.tmux)
token-finops status --format starship    # binding constraint only
token-finops status --format waybar      # JSON; also polybar, i3, xbar, json
```

`status` serves a cache (`~/.token-finops/last.json`) and rescans only with `--fresh` or when
the cache is older than `--max-age` seconds. Refresh it from one timer (`contrib/refresh/`) and let
every widget poll freely. Details: `../docs/TMUX.md`.

`status --notify` fires a desktop notification (macOS `terminal-notifier`/`osascript`, Linux
`notify-send`, Windows PowerShell best-effort) only when the binding constraint's status class
changes — never on every run — with the last-seen class recorded in
`~/.token-finops/notify-state.json`. See `../docs/statusline.html`.

## Self-audit

Claude Code writes one line per content block, so naive counting
over-reports by roughly 1.9x. `self-audit` deduplicates on
`(message.id, requestId)`, includes sub-agent transcripts, and breaks the
bill down by model — the model, not the raw token count, is what decides
the cost.

```bash
token-finops self-audit                     # latest session
token-finops self-audit --session <id-prefix>
token-finops self-audit --json              # machine-readable, for CI/PR checklists
```

## Local vs. cloud: savings and break-even

```bash
token-finops savings --list                          # available hardware/model/tariff keys
token-finops savings --hardware rtx-4090-workstation --model llama-3.3-70b
token-finops savings --power solar-de-feed-in --utilization 0.8
token-finops break-even --since 90d --replaceable-tiers haiku,sonnet
```

Solar is priced at the feed-in tariff you forgo, not at zero. Capex is
amortised per hour of *actual* inference. Only Haiku/Sonnet-class work
counts as replaceable by a local model — a 32B model does not do
Opus/Fable-class work. Hardware and energy numbers live in editable JSON
(`savings/hardware_profiles.json`, `savings/energy.json`) with sources and
review dates — measure your own box and overwrite them.

## Environment variables

Every adapter reads its data root from an override variable before falling
back to the tool's real default location. None of these are required —
they exist so you can point the CLI at a different install, a synthetic
fixture tree, or a non-default `$HOME`.

| Variable | Overrides | Default |
|---|---|---|
| `TOKEN_FINOPS_COPILOT_DB` | Copilot session-store DB path | `~/.copilot/session-store.db` |
| `TOKEN_FINOPS_DB` | (legacy alias, `sessions`/original CLI) Copilot DB path | `~/.copilot/session-store.db` |
| `CLAUDE_CONFIG_DIR` | Claude Code config root (`self-audit --config-dir` also sets this) | `~/.claude` |
| `CODEX_HOME` | OpenAI Codex CLI home | `~/.codex` |
| `GEMINI_CLI_HOME` | Gemini CLI home | `~/.gemini` |
| `HERMES_HOME` | Hermes Agent home | `~/.hermes` |
| `CLINE_CLI_HOME` | Cline CLI (non-VS Code) home | `~/.cline` |
| `TOKEN_FINOPS_CLINE_DIRS` | Cline/Roo/Kilo VS Code `globalStorage` roots | per-OS VS Code data dir |
| `TOKEN_FINOPS_OPENCODE_DB` | OpenCode/Kilo CLI sqlite DB path | `$XDG_DATA_HOME/opencode/opencode.db` |
| `XDG_DATA_HOME` | Base for the OpenCode DB default above | `~/.local/share` |
| `TOKEN_FINOPS_AIDER_DIRS` | Aider chat-history search roots | `~` |
| `TOKEN_FINOPS_AIDER_ANALYTICS` | Aider opt-in analytics JSONL path | `~/.aider/analytics.jsonl` |
| `CONTINUE_GLOBAL_DIR` | Continue.dev sessions root | `~/.continue` |
| `TOKEN_FINOPS_HARDWARE_JSON` | Override the `savings` hardware-profiles JSON | packaged `hardware_profiles.json` |
| `TOKEN_FINOPS_ENERGY_JSON` | Override the `savings` energy/tariff JSON | packaged `energy.json` |
| `TOKEN_FINOPS_ONLINE_CACHE` | Where `--online` caches provider responses | `~/.token-finops/online-cache.json` |

## Live quota: `--online` (opt-in)

```bash
token-finops report --online            # ask the provider instead of inferring locally
token-finops status --online            # same, and implies a rescan
```

Off by default — without the flag nothing leaves your machine. With it, four providers are
queried for their own current number: Copilot (`copilot_internal/user`), Claude Code
(`api.anthropic.com/api/oauth/usage`), Gemini CLI (`retrieveUserQuota`) and OpenRouter
(`/api/v1/key`, for Hermes). Credentials you already have — `gh auth token`/`$GITHUB_TOKEN`,
`~/.claude/.credentials.json`, `~/.gemini/oauth_creds.json`, `$OPENROUTER_API_KEY` — are read
to build one request header and are never written, refreshed or cached.

It **fails closed**: no network, no credential, a 429, an endpoint that changed shape — all of
it falls back silently to the normal offline report, with no error and no traceback. Responses
and failures are cached for 180 s (`~/.token-finops/online-cache.json`), which is what keeps a
polled status bar from getting rate-limited. Three of the four endpoints are
reverse-engineered and unversioned: `../docs/sources.md` has the table, the ADRs have the
reasoning.

## Settings

The variables above say *where the data is*. A second, smaller set says *how you want it
judged* — budget thresholds, the monthly cycle day, per-tool allowances, and a default
tool so you need not type `--tool claude_code` every time. Each has a `config.json` twin
in `~/.token-finops/config.json`, and one precedence rule applies to all of them:

```
explicit CLI flag  >  TOKEN_FINOPS_* env var  >  config.json  >  hardcoded default
```

| Variable | `config.json` key | Default |
|---|---|---|
| `TOKEN_FINOPS_WARN_AT` | `budget.warn_at` | `0.75` |
| `TOKEN_FINOPS_CRITICAL_AT` | `budget.critical_at` | `0.90` |
| `TOKEN_FINOPS_CYCLE_DAY` | `budget.cycle_day` | `1` |
| `TOKEN_FINOPS_BUDGET` | `budget.allowance.copilot` | per adapter |
| `TOKEN_FINOPS_ALLOWANCE` | `budget.allowance.<tool>` | per adapter |
| `TOKEN_FINOPS_WINDOW_HOURS` | `budget.window_hours` | per adapter |
| `TOKEN_FINOPS_DEFAULT_TOOL` | `default_tool` | none (all detected tools) |
| `TOKEN_FINOPS_CONFIG` | — | `~/.token-finops/config.json` |

```bash
TOKEN_FINOPS_WARN_AT=0.5 token-finops report   # try a stricter threshold for one run
token-finops doctor                            # print the settings actually in effect
```

Invalid values are reported once on stderr and fall back to the default rather than
aborting the run. Full schema, precedence details, and the rule that provider-reported
data (a real `resets_at`, a real `used%`) is never overridden by configuration:
[`../docs/CONFIG.md`](../docs/CONFIG.md).

## Documentation and design rules

This package is one component of the `token-finops` repository. For the
full guide, the read-only/fractions-not-dollars design rules, the
per-assistant Architecture Decision Records, and the 50 executable use
cases, see the repository root:

- [`../README.md`](../README.md) — project overview, design rules, related tools
- [`../docs/PLAN.md`](../docs/PLAN.md) — structured plan and status
- [`../docs/ADAPTERS.md`](../docs/ADAPTERS.md) — how to add an adapter
- [`../docs/adr/`](../docs/adr/) — one ADR per coding assistant
- [`../docs/SYNTH.md`](../docs/SYNTH.md) — synthetic telemetry generator
- [`../docs/USECASES.md`](../docs/USECASES.md) — every executable use case
- [`../docs/TMUX.md`](../docs/TMUX.md) — `status --format …` for tmux, starship, waybar, polybar, i3, SwiftBar
- [`../docs/INTEGRATIONS.md`](../docs/INTEGRATIONS.md) — editor / agent-native / desktop integrations (design doc)
- [`../CHANGELOG.md`](../CHANGELOG.md), [`../CONTRIBUTING.md`](../CONTRIBUTING.md)

## License

AGPL-3.0-or-later.

## Credit

The Copilot CLI budget/runway/session-break logic in this package is a
direct port of the original **token-finops-cli** by **tronicum**
([oh-my-agent-code/token-finops-cli](https://github.com/oh-my-agent-code/token-finops-cli)),
kept verbatim where possible. Everything else in this repository builds on
that foundation.
