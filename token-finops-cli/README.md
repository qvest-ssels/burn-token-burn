# token-finops-cli

A small, read-only CLI to keep an eye on your **GitHub Copilot CLI** token
usage and estimate a "runway" — how many days your monthly AI-unit budget
will last at your current burn rate.

It reads directly from the Copilot CLI's own local telemetry database
(`~/.copilot/session-store.db`, table `assistant_usage_events`) — no
external API calls, no scraping, nothing leaves your machine. The database
is opened in immutable/read-only mode so it can never interfere with a
live Copilot CLI session.

## Why

GitHub's Copilot usage-metrics REST API is enterprise-admin-only (requires
`manage_billing:copilot` / `read:enterprise` scopes) — there's no
individual-seat endpoint to query your own quota. This tool works around
that by reading the CLI's own local usage log and letting you supply your
own monthly budget number (from the Copilot billing page) so it can project
a runway estimate.

## Install

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv tool install token-finops-cli
token-finops --since 7d
```

Or from source, editable, in a venv:

```bash
uv venv
uv pip install -e ".[dev]"
.venv/bin/token-finops --since 7d
```

Or plain pip:

```bash
pip install token-finops-cli
```

## Usage

```bash
token-finops                      # full report, last 7 days (same as "report")
token-finops --since 30d          # last 30 days
token-finops --since all          # all-time
token-finops --session <id>       # filter to one session

# Budget / runway
token-finops --budget 50000 --cycle-day 1
token-finops --compact            # 2-line minimal output
token-finops --watch 5            # live-refreshing view every 5s
```

## Session history & break/gap reports

The `sessions` subcommand gives per-session archival/historical reporting
— useful for looking back at past sessions rather than just current
budget status:

```bash
token-finops sessions                       # list all past sessions
token-finops sessions --since 30d --limit 10
token-finops sessions --session <id>        # detailed break/gap report
token-finops sessions --session <id> --gap-minutes 60
token-finops sessions --totals              # ONE combined report across ALL sessions
```

The detailed per-session view detects "breaks" — gaps between requests
longer than `--gap-minutes` (default 30) — and reports active time (time
actually spent working) vs. idle/paused time (e.g. you closed the
terminal and came back the next day), alongside total elapsed wall-clock
time and a list of each pause with its start/end/duration.

## Try it without your own data (synthetic demo)

A small script generates a throwaway SQLite DB with fake usage events (same
columns the tool reads, nothing from your real `~/.copilot/session-store.db`
is ever touched):

```bash
python3 examples/generate_synthetic_db.py /tmp/demo.db --days 20
token-finops --db-path /tmp/demo.db --since 7d
token-finops --db-path /tmp/demo.db --compact
```

Or point the tool at any DB via the `TOKEN_FINOPS_DB` env var instead of
`--db-path`.

### Options

| Flag | Description |
|---|---|
| `--since {1d,7d,30d,all}` | Time window for the usage summary |
| `--session ID` | Filter to a single session |
| `--budget N` | Monthly AI-unit budget (default `50000`) — get this from your Copilot billing page |
| `--cycle-day N` | Day of month your billing cycle resets on (default `1`) |
| `--watch SECONDS` | Live-refreshing view, redraws every N seconds |
| `--compact` / `-c` | 2-line minimal output (budget bar + runway status) |
| `--verbose` / `-vv` | Full report (overrides `--compact`) |

`sessions` subcommand options:

| Flag | Description |
|---|---|
| `--since {1d,7d,30d,all}` | Time window for the session list (default `all`) |
| `--limit N` | Max sessions to list (default `20`) |
| `--session ID` | Show a detailed break/gap report for one session instead of the list |
| `--gap-minutes N` | Idle-gap threshold in minutes to count as a "break" (default `30`) |
| `--totals` | Print one combined report aggregated across ALL sessions matching `--since` (total requests/tokens/AI units, plus summed active/idle time and break count across every session) |

## What it measures

The "AI unit" is GitHub's own cost/usage unit for a mixed
included-quota + pay-per-use Copilot plan, taken from the
`total_nano_aiu` column (divided by `1e9`) — this matches what's shown on
the Copilot billing page. It is **not** raw token counts.

## Requirements

- Python 3 (standard library only — no dependencies)
- GitHub Copilot CLI installed and used at least once (so
  `~/.copilot/session-store.db` exists)

## Optional: use as a Copilot CLI skill

You can drop a `SKILL.md` into `~/.copilot/skills/token-finops-cli/` so any
Copilot CLI session can answer "what's my usage/runway?" on demand by
invoking this script. See the CLI's skills documentation for the expected
format.

## Roadmap

- [ ] Support reading local usage/session logs from other coding agents
      (e.g. Claude Code), so this becomes a general "agentic coding tool
      finops" CLI rather than Copilot-only.

## License

AGPL-3.0 — see [LICENSE](LICENSE).
