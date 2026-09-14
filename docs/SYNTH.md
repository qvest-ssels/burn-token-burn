# Synthetic telemetry generator

`token_finops_cli.synth` writes a complete, offline, fake-home-directory tree
that every adapter (and the whole CLI) can be pointed at — no real
`~/.copilot`, `~/.claude`, `~/.codex`, etc. ever touched. It exists so a demo,
a bug report, or this repo's own test suite can exercise the full adapter set
without anyone's real telemetry.

```
token-finops synth --out /tmp/demo-home
eval "$(token-finops synth --out /tmp/demo-home --print-env)" && token-finops report
```

(the CLI subcommand is a thin wrapper around `synth.generate()`; the same
thing is also available as a standalone script, `examples/generate_synthetic_db.py`.)

## What gets written, per tool

Reusing each adapter's own `build_synthetic_*()` (see `adapters/<tool>.py`),
under one `out_dir`:

| tool | path under `out_dir` | notes |
|---|---|---|
| `copilot` | `.copilot/session-store.db` | `assistant_usage_events` table, incl. optional `model`/`agent_id`/cache columns |
| `claude_code` | `.claude/projects/<project>/<session>.jsonl` + `<session>/subagents/agent-*.jsonl` | each API response written as two duplicated content-block lines (dedup exercise); also writes `.token-finops/quota.json` + `quota_history.jsonl` (status-line snapshots) |
| `codex` | `.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | `token_count` events with cumulative deltas **and** `rate_limits.primary`/`secondary`; one exact-duplicate line per session to exercise dedup |
| `gemini_cli` | `.gemini/tmp/<hash>/chats/session-*.jsonl` (+ one sub-agent transcript) and `.gemini/projects.json` | |
| `hermes` | `.hermes/state.db` | `sessions` + `session_model_usage`, mixing OpenRouter/Nous-portal (billed) and local Ollama (unbilled) rows |
| `opencode` | `.local/share/opencode/opencode.db` | `session` + `session_message`, mixing anthropic/openai/ollama |
| `cline` | `.config/Code/User/globalStorage/<extension-id>/tasks/<id>/ui_messages.json` | all three extension ids (Cline, Roo, Kilo) |
| `aider` | `.aider.chat.history.md` (+ `.aider/analytics.jsonl`) | one history file at `out_dir` itself, since Aider has no single root |
| `continue` | `.continue/sessions/sessions.json` + `<uuid>.json` | |

`generate()` returns a manifest: `{tool: {"path": ..., "events": N, "notes": [...]}}`.

## Scenarios

Pass `--scenario NAME` (default `steady`); see `synth/scenarios.py`:

| scenario | shape |
|---|---|
| `steady` | even usage across the period (identical output to each generator's pre-scenario behaviour) |
| `burst` | quiet, then the last 2 days run at ~5x normal volume |
| `exhausted` | Copilot's per-event AI-unit cost is scaled ~100x so total usage blows past even the largest real plan (Max, 20,000 AIU -- also the default allowance when none is given); Claude Code / Codex rolling-window `rate_limits` are pinned to 95-100% |
| `weekend` | zero usage on Saturday/Sunday (UTC) |
| `fresh` | first use was "yesterday" — usage before day-offset 2 is suppressed regardless of `--days` |
| `quiet` | a handful of events with long gaps between them |
| `subagent-heavy` | ~60% of Claude Code calls come from sub-agents instead of the main loop (vs. a 25% baseline) |

Each `build_synthetic_*()` gained an optional `scenario=` (and `now=`)
keyword; every existing call site (and every pre-existing test) keeps working
unchanged because `scenario="steady"` reproduces the exact prior output for
the same seed/day/count arguments.

## Env vars

Every adapter already exposed an override for its data root — `synth.env.env_for(out_dir)`
just points all of them at the same tree instead of introducing new ones:

```
HOME, USERPROFILE                out_dir itself (Aider's default search root is literally "~")
TOKEN_FINOPS_COPILOT_DB           out_dir/.copilot/session-store.db
CLAUDE_CONFIG_DIR                 out_dir/.claude
CODEX_HOME                        out_dir/.codex
GEMINI_CLI_HOME                   out_dir/.gemini
HERMES_HOME                       out_dir/.hermes
XDG_DATA_HOME                     out_dir/.local/share
TOKEN_FINOPS_OPENCODE_DB          out_dir/.local/share/opencode/opencode.db
TOKEN_FINOPS_CLINE_DIRS           out_dir/.config/Code/User/globalStorage
CONTINUE_GLOBAL_DIR               out_dir/.continue
TOKEN_FINOPS_AIDER_DIRS           out_dir
```

`token-finops synth --out DIR --print-env` prints these as `export VAR=...`
lines, so:

```bash
eval "$(token-finops synth --out /tmp/demo-home --scenario burst --print-env)"
token-finops report
```

runs the whole CLI against synthetic data in one line, in a fresh process.

**Caveat (Claude Code only):** `adapters.claude_code` resolves its
status-line `QUOTA_FILE`/`QUOTA_HISTORY_FILE` from `HOME` as module-level
constants *at import time*. The `eval && token-finops report` one-liner above
is a fresh process, so this resolves correctly. Reusing `env_for()` inside an
already-running process (as `tests/test_synth.py` does) additionally requires
monkeypatching `claude_code.QUOTA_FILE` / `claude_code.QUOTA_HISTORY_FILE` —
exactly as `tests/conftest.py`'s `home` fixture already does for its own
synthetic Claude Code fixtures.

## How the tests use it

`tests/test_synth.py`:

- generates each tool individually and scans it through its real adapter
  (`adapter.available()`, `adapter.events()`, model normalisation, USD
  estimates where expected);
- `"exhausted"` on Copilot drives `compute_runway()` to `CRITICAL`/`EXHAUSTED`;
- `"burst"` on Copilot makes the EMA daily burn exceed the cycle average
  (using an explicit `now` late in the calendar month, so the average has
  enough elapsed days to dilute against);
- `"subagent-heavy"` on Claude Code raises the sub-agent share of events;
- `"weekend"` produces no Monday-Friday violations;
- `token-finops synth --print-env` output is checked to contain every env
  var `env_for()` defines;
- a full `token-finops report --compact` against a fully generated synthetic
  home lists every tool that was generated.
