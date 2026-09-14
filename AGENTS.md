# AGENTS.md — working in this repository with a coding agent

This file is read by Claude Code, Codex, Copilot CLI and friends. Humans: see `README.md`.
For the day-to-day mechanics of working on this repo — running test subsets, synthetic
telemetry, debugging one adapter, the branch-per-task workflow, releasing — see
[`DEVELOPING.md`](DEVELOPING.md); this file stays the short list of rules.

## What this repo is

`burn-token-burn` extends Stefan's **token-finops-cli** (GitHub Copilot CLI budget runway, `token-finops-cli/`) into a modular, read-only tracker for every coding assistant that leaves telemetry on disk, plus a local-vs-cloud savings estimator and a guide. Decisions per assistant live in `docs/adr/`; the field tables in `docs/ADAPTERS.md` are the source of truth for parsers.

## Agentic workflow: branch + PR, not direct-to-main

Sub-agent / background-agent work should fan out whenever the task allows it (independent files
or independent pieces of a larger task = independent agents). Each agent works on its own
`feature/agentic/<topic-or-task>` branch and opens a PR back to `main` instead of pushing directly
to `main` — the coordinating session then gives the human a PR link to preview/approve, rather than
changes landing on `main` unreviewed. Keep PRs scoped to what one agent actually touched; don't
bundle unrelated agents' work into one PR just because they ran concurrently.

## Ground rules

1. **Read-only against tool data.** Never write to `~/.copilot`, `~/.claude`, `~/.codex`, `~/.gemini`, `~/.hermes` or any other assistant's store. SQLite is opened with `immutable=1` via `adapters.base.sqlite_readonly()`.
2. **Standard library only** in the package. No runtime dependencies. Dev tooling (`pytest`, `ruff`) is fine.
3. **Python ≥ 3.10.** Use `uv` for environments (see below). Never install into the system interpreter.
4. **Budgets are fractions, never dollars.** USD is a labelled *API-equivalent* estimate. Do not sum units across tools; roll up as the *binding constraint*.
5. **One ADR per assistant.** Adding or changing support for an assistant means updating its ADR in `docs/adr/` (status, tier, open questions) in the same PR.
6. **Every number has a source and a review date** (`docs/sources.md`, `savings/*.json`). If you cannot cite it, mark it as an estimate.
7. **Schema drift is normal.** Parsers use field-alias lists, skip unparsable lines, never raise on one bad record, and ship a synthetic fixture builder plus a test.
8. **Right-size the model.** Menial work (markdown polish, fixtures, boilerplate adapters) goes to a cheap model/sub-agent; architecture and normalisation logic to the strongest one. Run `token-finops self-audit` at the end of a session and paste the by-model table into the PR description — this repo eats its own dog food.

## Environment

```bash
uv venv                                   # creates .venv (Python from .python-version)
uv pip install -e "token-finops-cli[dev]" # editable install of the package + pytest/ruff
source .venv/bin/activate                 # or prefix commands with `uv run`
```

## Commands

```bash
uv run pytest -q                 # all tests (synthetic fixtures, no real tool data needed)
uv run ruff check .              # lint (line length 110)
uv run token-finops adapters     # which data sources exist on this machine
uv run token-finops report       # runway per tool
uv run token-finops self-audit   # what the current Claude Code session cost, incl. sub-agents
```

CI (`.github/workflows/ci.yml`) runs ruff + pytest on 3.10–3.13. Keep it green.

## Layout

```
token-finops-cli/          Stefan's original tool as a git subtree (full history) — the package lives here
  src/token_finops_cli/
    cli.py                 entry point (report / sessions / self-audit / savings / break-even / collect-statusline / adapters)
    core/                  model.py (UsageEvent, QuotaSnapshot, BudgetPolicy, Runway), runway.py, pricing.py
    adapters/              one module per assistant, registered via @register; base.py has the read-only helpers
    savings/               local-vs-cloud estimator + editable hardware_profiles.json / energy.json
    report.py              plain-ASCII rendering (no Unicode block glyphs — some terminal fonts drop them)
  tests/                   pytest, one file per adapter + core + cli
docs/
  adr/                     one ADR per coding assistant (status, tier, data source, open questions)
  guide/                   The Qvest Digital Guide to Token Burning
  ADAPTERS.md              how to write an adapter + verified field tables
  landscape.md             related tools we point to instead of re-implementing
  sources.md               every price/quota/endpoint with source and review date
  PLAN.md                  the structured plan and current status
```

## How to add an assistant

1. Read its ADR (`docs/adr/00NN-<assistant>.md`). If none exists, write one first (copy the template from an existing ADR, status *Proposed*).
2. Implement `adapters/<tool>.py` following `docs/ADAPTERS.md` — `scan()`, optional `quota()`, `default_policy()`, `build_synthetic_<tool>()`.
3. Add `tests/test_<tool>.py` against the synthetic fixture (event count, dedup, model normalisation, USD > 0 or `None` for local models, policy unit).
4. Register it in `adapters/__init__.py::all_adapters()`.
5. Update the ADR status to *Accepted* and the support table in `README.md`.

## Commit messages

Imperative subject, body explains *why*. When a coding agent authored the change, keep the attribution trailers it adds (`Co-Authored-By`, `Claude-Session`, etc.).

## Things not to do

- Do not add network calls without an explicit `--online` flag and an ADR note; default runs must work offline.
- Do not vendor third-party parsers; reuse ideas, cite them in `docs/landscape.md`.
- Do not "fix" numbers in `docs/guide` by hand — regenerate them with `self-audit` and state the snapshot date.
- Do not commit `__pycache__`, `.venv`, bundles, or real telemetry files (there are anonymised fixtures for that).
- Do not use the system `/tmp` for scratch state (synthetic homes, throwaway venvs, cast recording
  scaffolding, etc.) — use the repo-local `./tmp/` instead (gitignored). When recording an
  asciinema cast (`docs/casts/`), never let a real absolute path leak into the committed `.cast`
  file — sanitize it to `~/...` afterward, as if it were a real user's home directory (see
  `docs/casts/README.md` for the recipe). Public-facing docs (`docs/index.html`, `README.md`) must
  read as a plain user journey — never mention `./tmp`, virtualenvs, or sanitization mechanics
  there; that plumbing belongs only in `docs/casts/README.md`.
