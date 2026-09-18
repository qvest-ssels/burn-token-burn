# DEVELOPING.md — working on this repository day to day

This is a stdlib-only Python package (`token-finops-cli/`) with a runway engine, per-adapter telemetry parsers, a local-vs-cloud savings estimator, and documentation. The ground rules that shape development are in [`AGENTS.md`](AGENTS.md); the mechanics of adding a new assistant are in [`CONTRIBUTING.md`](CONTRIBUTING.md); the design rationale for the repo's split between cloud and local Claude Code sessions is in [`AUTOCODING.md`](AUTOCODING.md). This file is the hub for day-to-day work: environment setup, running tests, debugging adapters, the branch-per-task workflow, and where docs live.

## Environment

```bash
uv venv                                   # creates .venv (Python from .python-version)
uv pip install -e "token-finops-cli[dev]" # editable install of the package + pytest/ruff
source .venv/bin/activate                 # or prefix commands with `uv run`
```

CI (`.github/workflows/ci.yml`) runs pytest and ruff on Python 3.10, 3.11, 3.12, and 3.13. Keep it green.

The package has no runtime dependencies (standard library only, per AGENTS.md rule 2). Dev tooling — `pytest>=8.0`, `ruff>=0.6` — is listed in `token-finops-cli/pyproject.toml`'s `[project.optional-dependencies].dev` and is fine. Ruff line length is 110 characters.

## Running tests

```bash
uv run pytest -q                         # all tests (784 total, synthetic fixtures only, no network)
uv run ruff check .                      # lint
uv run token-finops adapters             # detect which tool data exists on this machine
uv run token-finops report                # runway per tool
```

Useful subsets (use with `uv run pytest -q -k PATTERN`):

| Target | Pattern | What it does |
|---|---|---|
| One use case | `UC-13` | Runs test_usecases.py::test_*[UC-13] — the one named use case |
| All use cases | `test_usecases` | 50 use cases, one per tool mix; one line per test |
| Burn module | `burn` | Maxing multiplier, weekly/monthly tables, efficiency metric, partial periods |
| One adapter | `copilot` or `claude_code` or `codex` | Test files like test_copilot.py, test_claude_code.py; fixtures only |
| E2E matrix | `test_e2e_matrix` | Shells out to `token-finops report` subprocesses with synthetic data; slower |
| Robustness / fuzz | `test_robustness` | Non-UTF-8 bytes, corrupt SQLite, drifted schemas; all adapters |
| CLI smoke | `test_cli_smoke_workflow` | Validates `.github/workflows/cli-smoke.yml` YAML and documented `token-finops` commands against doc strings; pure string checks, no network |

## Working against real vs. synthetic telemetry

By design, adapters are read-only against real tool data (AGENTS.md rule 1), so day-to-day development and **all tests use `token-finops synth`** to fabricate a fake-home tree instead of reading from `~/.claude`, `~/.copilot`, etc.

Typical workflow:

```bash
# Generate synthetic data once
token-finops synth --out /tmp/demo-home --tools copilot,claude_code --scenario burst --print-env

# Point adapters at it for this shell session
eval "$(token-finops synth --out /tmp/demo-home --tools copilot,claude_code --scenario burst --print-env)"

# Now run reports against the fake home
token-finops report
token-finops report --json | jq .
```

(The test suite itself doesn't need this — each test builds its own synthetic fixture in a `tmp_path`, per adapter. This `eval`/`--print-env` idiom is for exploring the CLI interactively.)

**Synth CLI options:**
- `--out DIR` (required): write the fake-home tree here
- `--tools t1,t2` (default: all): comma-separated subset (copilot, claude_code, codex, gemini_cli, hermes, opencode, cline, aider, continue)
- `--days N` (default: 14): how many days of history
- `--scenario NAME` (default: steady): one of steady, burst, exhausted, weekend, fresh, quiet, subagent-heavy (see SYNTH.md for shapes)
- `--seed N` (default: 42): RNG seed for reproducible fixtures
- `--print-env`: print `export VAR=...` lines for the eval idiom above

**Per-tool environment variables** (set by `synth --print-env`; override one to point a single adapter at a fixture while testing):

| Variable | Tool | Default when unset |
|---|---|---|
| `HOME`, `USERPROFILE` | aider (search root) | system home |
| `TOKEN_FINOPS_AIDER_DIRS` | aider (root override) | `~` |
| `CLAUDE_CONFIG_DIR` | claude_code | `~/.claude` |
| `TOKEN_FINOPS_CLINE_DIRS` | cline (root override) | `~/.config/Code/User/globalStorage` |
| `CODEX_HOME` | codex | `~/.codex` |
| `CONTINUE_GLOBAL_DIR` | continue | `~/.continue` |
| `TOKEN_FINOPS_COPILOT_DB` | copilot | `~/.copilot/session-store.db` |
| `GEMINI_CLI_HOME` | gemini_cli | `~/.gemini` |
| `HERMES_HOME` | hermes | `~/.hermes` |
| `XDG_DATA_HOME` | opencode (data root) | `~/.local/share` |
| `TOKEN_FINOPS_OPENCODE_DB` | opencode (DB override) | `~/.local/share/opencode/opencode.db` |

See `docs/SYNTH.md` for the full generator documentation, including which on-disk paths and table/file formats each adapter writes.

These point adapters at *data*. The separate set of **settings** variables
(`TOKEN_FINOPS_WARN_AT`, `TOKEN_FINOPS_CRITICAL_AT`, `TOKEN_FINOPS_CYCLE_DAY`,
`TOKEN_FINOPS_BUDGET`, `TOKEN_FINOPS_ALLOWANCE`, `TOKEN_FINOPS_WINDOW_HOURS`,
`TOKEN_FINOPS_DEFAULT_TOOL`, `TOKEN_FINOPS_CONFIG`) and their `~/.token-finops/config.json`
twins are documented in `docs/CONFIG.md`. The test suite neutralises all of them via the
autouse `isolated_config` fixture in `tests/conftest.py`, so a developer's own settings can
never change a test result — use the `write_config` fixture to exercise them deliberately.

## Debugging one adapter

1. Generate synthetic data for that tool only:
   ```bash
   eval "$(token-finops synth --out /tmp/fixture --tools copilot --scenario steady --print-env)"
   ```

2. Run the adapter's tests with output:
   ```bash
   uv run pytest -s token-finops-cli/tests/test_copilot.py
   ```

3. Call the adapter directly:
   ```bash
   uv run token-finops adapters   # see if the tool is detected
   uv run token-finops report --tool copilot --json | jq .
   ```

4. Add a `print()` statement in the adapter source or use `-s` flag (above) to see stdout. The adapter lives in `token-finops-cli/src/token_finops_cli/adapters/<tool>.py`.

Adding a **new** adapter is CONTRIBUTING.md's job (ADR + implementation + tests + registration); this section is for debugging an existing one.

## The branch-per-task workflow

Work packages with ready-to-pick-up branches live in `claude-tasks.md`. Pick one, create a branch locally from `main`, do the work, and **never commit directly to main**. When ready:

```bash
cd token-finops-cli
uv run pytest -q            # must pass
uv run ruff check .          # must pass
```

Then:

```bash
uv run token-finops self-audit  # run at end of session to get the by-model table
```

Open a PR against `main` and paste the `self-audit` by-model table (showing calls, tokens, API-equivalent per model) into the PR description. The checklist is in `CONTRIBUTING.md`; the key point is that this repo dogfoods its own tool.

## Releasing

See `.github/workflows/release.yml` and `claude-tasks.md` task T-05. Releasing is a human step: configure PyPI trusted publishing for the GitHub repo, then locally run `git tag v*.*.* && git push --tags`. CI then builds and publishes automatically. Do not script this casually.

## Where the docs are

Start at `docs/README.md` for the full documentation index. This file is the developer hub; the rest live under `docs/` and cover architecture decisions, adapter implementation details, the synthetic fixture format, end-user install instructions, integration surfaces, pricing sources, and the Qvest Digital Guide to Token Burning.
