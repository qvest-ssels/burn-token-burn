# Configuration — `~/.token-finops/config.json` and `TOKEN_FINOPS_*`

Everything on this page is **opt-in**. The config file does not exist until you create
it, and every setting keeps the value it had before it was configurable, so a machine
with no config file behaves exactly as it always did.

Two kinds of environment variable live in this project and it is worth keeping them
apart:

- **Data-location variables** (`TOKEN_FINOPS_COPILOT_DB`, `CLAUDE_CONFIG_DIR`,
  `CODEX_HOME`, …) tell an adapter *where a tool's telemetry is*. They are documented
  in [`../token-finops-cli/README.md`](../token-finops-cli/README.md#environment-variables)
  and [`../DEVELOPING.md`](../DEVELOPING.md).
- **Settings variables** (`TOKEN_FINOPS_WARN_AT`, `TOKEN_FINOPS_DEFAULT_TOOL`, …) tell
  the tool *how you want the numbers judged and displayed*. Those are this page, and
  they all have a `config.json` twin.

## Precedence

One rule, everywhere:

```
explicit CLI flag  >  TOKEN_FINOPS_* env var  >  config.json  >  hardcoded default
```

A flag you typed always wins. An env var beats the file, so you can try a setting for
one command (`TOKEN_FINOPS_WARN_AT=0.5 token-finops report`) or pin one per shell/tmux
pane without editing anything. The file is the durable choice. The hardcoded default is
what everyone gets who has done none of the above.

The CLI tier is installed once in `main()`, before any subcommand runs, so a flag
applies no matter how deep in the call stack the budget policy is finally built.

## The file

Default location `~/.token-finops/config.json` — the same directory
`collect-statusline` already writes `quota.json` into. Point `TOKEN_FINOPS_CONFIG` at
another path to override it (handy for a per-project or per-machine settings file).

Every key is optional; a file containing only the keys you care about is normal.

```json
{
  "default_tool": "claude_code",
  "statusline": { "show_subagents": true },
  "budget": {
    "warn_at": 0.80,
    "critical_at": 0.95,
    "cycle_day": 15,
    "allowance": { "copilot": 3000, "gemini_cli": 1000 },
    "window_hours": { "claude_code:5h": 26, "codex": 30 }
  }
}
```

## Every setting

| `config.json` key | Env var | CLI flag | Default | What it does |
|---|---|---|---|---|
| `budget.warn_at` | `TOKEN_FINOPS_WARN_AT` | — | `0.75` | Fraction of a window at which a tool's status turns `WARN`. |
| `budget.critical_at` | `TOKEN_FINOPS_CRITICAL_AT` | — | `0.90` | Fraction at which it turns `CRITICAL`. |
| `budget.cycle_day` | `TOKEN_FINOPS_CYCLE_DAY` | `--cycle-day` | `1` | Day of the month (UTC) a calendar-month budget resets on. `1`–`28`. |
| `budget.allowance` | `TOKEN_FINOPS_BUDGET` (Copilot), `TOKEN_FINOPS_ALLOWANCE` (everything else) | `--budget`, `--allowance` | per adapter | Your plan's allowance in the tool's native unit. A number applies to every tool; an object keys it per tool. |
| `budget.window_hours` | `TOKEN_FINOPS_WINDOW_HOURS` | — | per adapter | How long a *rolling* window is assumed to be. Key it `"<tool>"` or, more precisely, `"<tool>:<window_id>"` (`claude_code:5h`, `claude_code:7d`). |
| `default_tool` | `TOKEN_FINOPS_DEFAULT_TOOL` | `--tool` | none (all detected tools) | The tool `--tool` defaults to when you pass none. |
| `statusline.show_subagents` | — | — | `false` | Append `N agents · T tokens` to `collect-statusline`'s output. |
| — | `TOKEN_FINOPS_CONFIG` | — | `~/.token-finops/config.json` | Where the config file itself lives. |

### Thresholds

`warn_at` and `critical_at` are fractions of a window, never dollars (see
[`AGENTS.md`](../AGENTS.md) ground rule 4). They apply to **every** tool at once —
there is no per-tool threshold — and they are what turns `OK` into `WARN` into
`CRITICAL` in `report`, `status`, and the colour of `collect-statusline`'s progress
bars.

```bash
TOKEN_FINOPS_WARN_AT=0.5 TOKEN_FINOPS_CRITICAL_AT=0.6 token-finops report
```

They are not the only thing that can produce a `CRITICAL`: a tool projected to exhaust
its budget *before the window resets* is critical regardless of how little of it has
been used so far. Raising the thresholds does not switch that off.

### Allowances

`--budget` is Copilot's monthly AI-unit allowance; `--allowance` is the equivalent for
every other tool, in that tool's own unit. The config file can express both, and can be
specific about which tool it means:

```json
{ "budget": { "allowance": { "copilot": 3000, "gemini_cli": 1000 } } }
```

A plain number (`"allowance": 500`) applies to every tool, which is rarely what you
want across heterogeneous units — prefer the object form.

### Rolling windows, and what config may *not* override

`budget.window_hours` sets how long a rolling window is assumed to be. It exists
because that span is the one thing no provider reports.

What providers *do* report is the **reset time** — Claude Code's statusline payload and
Codex's rollout `rate_limits` both carry a real `resets_at`, and `collect-statusline`
records it. That timestamp is measured data and always wins: a configured
`window_hours` shapes where the window is assumed to *start* (and therefore the
elapsed-fraction and pace figures), but it never moves a reset time the tool told us
about. The same holds for the used percentage: a provider-reported `used%` is never
overridden by anything in this file.

> **Claude Code note.** The `rate_limits` block only appears in the statusline payload
> when the session is billed against a subscription window (Pro / Max). Without it
> there is nothing to apply a threshold to and the 5h/7d status stays `UNKNOWN` — see
> [`adr/0002-claude-code.md`](adr/0002-claude-code.md). Configuring thresholds does not
> conjure a quota where the provider reports none.

### Default tool ("default agent")

If you mostly care about one assistant, name it once:

```json
{ "default_tool": "claude_code" }
```

…and `report`, `sessions`, `status`, `doctor`, `burn`, `cost-per-token` and
`break-even` all behave as if you had typed `--tool claude_code`. Passing `--tool`
explicitly always wins, and passing a *different* tool works exactly as before.

Run `token-finops adapters` for the valid names. A name no adapter answers to is
ignored with a warning on stderr rather than producing a silently empty report.

## Invalid values never abort the run

A value that is out of range, unparsable, or self-contradictory (`warn_at` ≥
`critical_at`) is reported once on stderr and then *skipped* — resolution simply carries
on down the precedence chain to the next tier that has an opinion, ending at the
hardcoded default:

```
$ TOKEN_FINOPS_WARN_AT=1.5 token-finops report
token-finops: ignoring $TOKEN_FINOPS_WARN_AT warn_at='1.5' -- outside 0.0 < x <= 1.0
```

So a bad env var falls back to your `config.json` value if you have one, and to `0.75`
if you do not. A bad setting never promotes itself past a good one.

This is a deliberate choice over raising at startup. `token-finops` is a read-only
observability tool that people wire into shell prompts, tmux status bars and Claude
Code's `statusLine.command`, where it is re-executed on *every* prompt — a hard failure
there would take out the prompt itself over a typo in an optional settings file. The
warning is printed once per process (not once per adapter), names the source, the key
and the value, and the tool then behaves like a machine with no config at all. Nothing
degrades silently.

`warn_at` and `critical_at` are validated as a pair: if the pair is incoherent, *both*
fall back, rather than leaving a policy in which `WARN` could never fire before
`CRITICAL`.

A missing, unreadable, corrupt, or non-object config file is treated as "no settings" —
the same guarantee the original statusline-only reader gave.

## Checking what is actually in effect

`token-finops doctor` prints the resolved settings, after flags, env vars and the file
have been folded together:

```
  config file: ~/.token-finops/config.json (loaded)
      thresholds: WARN at 80% of the window, CRITICAL at 95%
      cycle day:  15 (monthly-cycle tools, UTC)
      default tool: claude_code
      allowance overrides: copilot=3000, gemini_cli=1000
```

## Backward compatibility

`~/.token-finops/config.json` previously held exactly one setting,
`{"statusline": {"show_subagents": true}}`. That file still works unchanged; the
`statusline` section is simply one section among several now.
