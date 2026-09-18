# tmux, prompts and status bars

`token-finops status` is the one renderer every status surface uses. It reads a cache
(`~/.token-finops/last.json`) and only rescans your telemetry with `--fresh` or when the cache is
older than `--max-age` seconds (default 300). Keep the cache warm with **one** timer
(`contrib/refresh/`) and let every widget poll the cache as often as it likes.

```
$ token-finops status                     # plain, binding tools only
CC 61% 2h! | CX 17% 3h | CP 29% 41d | GM 6% inf | binds: CC

$ token-finops status --all               # include usage-only tools without an allowance
$ token-finops status --format tmux       # tmux colour escapes
$ token-finops status --format starship   # binding constraint only, e.g. "CC 61% 2h!"
$ token-finops status --format waybar     # JSON {text, tooltip, class, percentage}
$ token-finops status --format polybar    # %{F#hex} colour tags
$ token-finops status --format i3         # i3blocks: text / short / colour
$ token-finops status --format xbar       # SwiftBar/xbar menu-bar plugin output
$ token-finops status --format json       # the cache itself + stale_seconds
```

Segments read `<tool> <used%> <runway><flag>`: `CP` Copilot, `CC` Claude Code, `CX` Codex,
`GM` Gemini CLI, `HM` Hermes, `OC` OpenCode, `CL` Cline/Roo/Kilo, `AI` Aider, `CT` Continue.
Flags: `!` WARN, `!!` CRITICAL, `X` EXHAUSTED, `?` UNKNOWN (Claude Code without a status-line
snapshot yet). `binds:` names the tool that runs out first.

## tmux

Plugin (TPM or manual):

```tmux
# ~/.tmux.conf
set -g @token_finops_format 'tmux'     # tmux | plain | starship
set -g @token_finops_interval 60
run-shell ~/workspace/burn-token-burn/contrib/tmux/token-finops.tmux
```

Or one line without the plugin:

```tmux
set -g status-interval 60
set -g status-right '#(token-finops status --format tmux --max-age 0) %H:%M'
```

A live pane instead of a status segment (the original `token-finops-cli` use case):

```bash
tmux split-window -v -l 3 'token-finops report --compact --watch 30'
```

## starship, zsh, fish

See `contrib/starship/README.md`. For a bare zsh prompt: `RPROMPT='$(cat ~/.token-finops/last-line.txt 2>/dev/null)'`.

## waybar / polybar / i3blocks / SwiftBar

Recipes in `contrib/waybar/README.md` and `contrib/xbar/token-finops.5m.sh`.

## Claude Code status line

Different mechanism, same directory: `collect-statusline` stores the rate-limit percentages
Claude Code pushes into the status line — that is what makes `CC 61% 2h!` possible at all.

```jsonc
// ~/.claude/settings.json
{ "statusLine": { "type": "command", "command": "token-finops collect-statusline" } }
```

The line itself looks like `claude-sonnet-5 | 5h [####------]  40.0% | 7d [#---------]  12.0%`
(green/yellow/red at the same 75 %/90 % thresholds as `report` — move them with
`budget.warn_at`/`budget.critical_at`, see [`CONFIG.md`](CONFIG.md)). Opt in to a sub-agent count and
token total for the current session — `... | 2 agents · 8.4k tokens` — by creating
`~/.token-finops/config.json`:

```json
{ "statusline": { "show_subagents": true } }
```

That is one section of the shared settings file — budget thresholds, a default tool and
allowance overrides live in the same place; [`CONFIG.md`](CONFIG.md) documents all of it.

Off by default: it parses `<session>/subagents/agent-*.jsonl` on every refresh, which is extra
disk I/O most setups don't need. Requires Claude Code's payload to carry `transcript_path` (it
does in current releases); with none, or no sub-agents on disk, the segment is simply omitted.

## Why a cache

A Claude Code project directory can hold hundreds of MB of JSONL. `report` rescans it; a status
bar polling every 5 s must not. `status --max-age 0` never rescans; the refresher timer does,
every two minutes. Widgets can grey out stale data using `stale_seconds` from `--format json`.
