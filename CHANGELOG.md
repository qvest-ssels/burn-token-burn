# Changelog

All notable changes to this project are documented here, in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.0] — 2026-09-24

### Added

- **`token-finops doctor`** — per-adapter found/empty/missing diagnosis with the exact paths
  probed and one actionable hint each, so a fresh install's empty `report` output explains
  itself instead of just looking broken.
- **`--online`** on `report`/`status` — opt-in live quota fetchers for GitHub Copilot,
  Claude Code, Gemini CLI and Hermes (OpenRouter), stdlib `urllib` only, cached >= 180 s in
  `~/.token-finops/online-cache.json`, hard-fail closed to the existing offline path on any
  error (never on by default; a fetch failure is invisible to the user). Codex needs no
  fetcher — it already writes `rate_limits` to disk itself.
- **Configurable budget policy** — `~/.token-finops/config.json` + `TOKEN_FINOPS_*` env vars
  override the `warn_at`/`critical_at` thresholds, the Copilot `cycle_day`, per-tool
  `allowance`, and rolling `window_hours`, plus a `default_tool` so `--tool` doesn't need
  repeating on every call. One precedence rule everywhere: explicit CLI flag > env var >
  config.json > hardcoded default; a real provider-reported reset time or usage percentage
  always outranks a configured fallback. See `docs/CONFIG.md`. `--budget`/`--allowance`/
  `--cycle-day` are now accepted consistently across `report`/`sessions`/`doctor`/`status`/
  `burn`/`cost-per-token` instead of only `report`/`status`.
- **`token-finops savings --co2`** — an opt-in green-IT block comparing local (measured,
  from the chosen power tariff) against cloud (an explicitly labelled order-of-magnitude
  *estimate*, since no cloud AI provider publishes energy-per-token) gCO2e per 1M tokens,
  with `--cloud-region` for different grid mixes. Every figure and its confidence level is
  sourced in `docs/CO2_ESTIMATE.md`.
- **`savings --own-hardware`** reframed as **Hosting vs. Licensing** — once a box is already
  bought, capex is a sunk cost; the comparison that matters is the ongoing cost of running it
  (energy + a flat, clearly-labelled `--management-overhead` assumption for wear/maintenance,
  default 10%) against paying per token/plan.
- A **MacBook Pro 16" M4 Max, 48 GB** hardware profile — the first laptop entry (previously
  desktop/mini/studio machines and PC towers only).
- **Claude Code `/runway` skill** (`contrib/claude-code/runway/`) and the equivalent Codex
  custom prompt (`contrib/codex/prompts/runway.md`) — checks the token runway before an
  agentic session fans out expensive sub-agent work.
- **Shell completions** (bash/zsh/fish) under `contrib/completions/`, with a drift-guard test
  against the real argparse parser.
- **ADR-0013**: Claude Desktop / Cowork (macOS) investigation — Desktop chat has no local
  telemetry (reference-only), but the account-wide 5h/7d quota is cached offline in
  `plan-usage-history.json`, and on-computer Cowork sessions mirror full token/cost records to
  `local-agent-mode-sessions/**/audit.jsonl` (a full adapter is a proposed follow-up).
- **GitHub issue forms and a PR template** — five targeted forms (parser/adapter drift, bug,
  new-assistant request routed into the ADR question set, feature request, stale/wrong number)
  instead of a generic bug tracker, matching this project's own sourcing discipline.
- A public **GitHub Pages docs site** (multi-page, one page per command, real asciinema
  recordings throughout) plus a long-form **CO2 research page** on LLM inference energy
  accounting.
- Editor integrations that read the `status` cache read-only (never trigger a rescan):
  a Neovim plugin (`contrib/nvim/token-finops.nvim`, lualine/heirline component +
  `:TokenFinops` + `:checkhealth`), a VS Code status-bar extension (`contrib/vscode/`), and
  an Emacs package (`contrib/emacs/token-finops.el`).
- A drafted **Homebrew formula** (`contrib/homebrew/token-finops-cli.rb`) with a CI smoke test
  that actually builds/installs it on a macOS runner; a weekly `pypi-smoke.yml` that installs
  the real published wheel and exercises it end to end.

### Fixed

- **`self-audit` across Claude Code context-compaction boundaries** — a compacted session used
  to silently report as two disconnected totals instead of one; transcript segments sharing a
  session id are now stitched and deduplicated together, with `segments: N` in the header.
- Copilot synthetic-data scale rebalanced to match real plan sizes (`synth --scenario steady`
  now reads as a plausible ~20% of a Pro allowance instead of blowing past even Max's monthly
  allowance in two weeks).

## [0.3.0] — 2026-09-05

Everything since 0.2.0: the original Copilot-only tool becomes a modular,
multi-assistant runway tracker plus a local-vs-cloud savings estimator.

### Added

- **Nine adapters**, each with `scan()`/`events()`, an optional `quota()`,
  a `default_policy()`, a synthetic-fixture builder, and its own test file:
  GitHub Copilot CLI (original, ported), Claude Code, OpenAI Codex CLI,
  Gemini CLI, Hermes Agent, OpenCode/Kilo CLI, Cline/Roo/Kilo (VS Code),
  Aider, Continue.dev.
- **Shared runway engine** (`core/runway.py`, `core/model.py`) that never
  sums heterogeneous units across tools; `binding_constraint()` reports
  which tool's budget runs out first.
- **`token-finops collect-statusline`** — a Claude Code `statusLine.command`
  hook that persists `rate_limits` snapshots to `~/.token-finops/quota.json`
  and `quota_history.jsonl`, giving Claude Code (which only ever exposes a
  percentage) a real burn-rate and runway estimate from two or more
  snapshots in the same window.
- **`token-finops self-audit`** — per-session cost report for Claude Code,
  deduplicated on `(message.id, requestId)`, including sub-agent
  transcripts and a by-model breakdown; `--json` for scripting.
- **`token-finops savings`** and **`token-finops break-even`** — local
  ($/hardware+power) vs. cloud (API-equivalent) cost estimator, with
  editable, sourced `hardware_profiles.json` / `energy.json`; break-even
  replays real usage (Haiku/Sonnet-class only) against a box's amortised
  cost.
- **`token-finops synth`** — writes a complete synthetic fake-home tree
  (all nine tools) for offline demos, bug reports and the test suite, with
  seven burn-profile scenarios (`steady`, `burst`, `exhausted`, `weekend`,
  `fresh`, `quiet`, `subagent-heavy`) and `--print-env` for a one-line
  `eval "$(token-finops synth ...)" && token-finops report` demo.
- **`token-finops adapters`** — lists which data sources were found on the
  current machine and where each one looked.
- One **Architecture Decision Record per coding assistant** (`docs/adr/`),
  recording data source, support tier, offline-quota availability and open
  questions.
- **394 tests** and **50 executable use cases** (`docs/USECASES.md`,
  generated from `tests/test_usecases.py`), covering every adapter, the
  runway engine, the savings estimator, and multi-tool report/JSON output.
- `AGENTS.md` / `CLAUDE.md`, `docs/PLAN.md`, `docs/ADAPTERS.md`,
  `docs/landscape.md`, `docs/sources.md`, and the six-chapter
  `docs/guide/` ("The Qvest Digital Guide to Token Burning").
- `status` subcommand: one renderer family (`--format plain|tmux|starship|waybar|polybar|i3|xbar|json`)
  over a cache in `~/.token-finops/last.json` (`--fresh`, `--max-age`, `--all`), so status bars never
  rescan telemetry; `contrib/` with a tmux plugin, systemd/launchd refresh timers and
  starship/waybar/SwiftBar recipes; `docs/TMUX.md`.
- `docs/INTEGRATIONS.md` — design for editor, agent-native (`/runway`) and desktop surfaces.
- **`token-finops cost-per-token`** — $ per 1M tokens by tool and model: the real
  provider list price plus your realized blended rate for every pay-per-token tool
  (Claude Code, Codex, Gemini CLI, Hermes, OpenCode, Cline/Roo/Kilo, Aider,
  Continue.dev); for GitHub Copilot, which bills in AI credits with a per-model
  request multiplier and has no official $/token rate at all, a clearly labelled
  *derived* ratio (credits converted to USD at $0.01/credit, divided by observed
  tokens) instead — never mixed in with a real price; see `docs/COST_PER_TOKEN.md`.
- **`token-finops burn`** — the maxing multiplier (API-equivalent per 30 days / plan price,
  against a bundled, overridable plan catalogue), plan-months, a weekly/monthly token table
  (`--by day|week|month`), history recording and merging (`--record`/`--history`) so `--by` can
  reach past a tool's own retention, a burn-efficiency block (`--efficiency`/`--nerdy`: cache hit
  ratio, frontier/sub-agent share, routing dividend, ...), a prepaid/committed-spend rate
  (`--rate IN/OUT[/CR[/CW]]`), and a flat promo discount (`--discount`); see `docs/BURN.md`.
- **Colourised `collect-statusline`** — the Claude Code status-line hook now renders a
  hash-progress-bar per window (ANSI green/yellow/red at the 75 %/90 % warn/critical thresholds)
  with a bold model name, plus an opt-in sub-agent count/token summary
  (`~/.token-finops/config.json`, `{"statusline": {"show_subagents": true}}`).
- **`self-audit` across context-compaction** — stitches every transcript segment sharing a
  session id (main + `subagents/`), deduplicates globally instead of per-file, and reports
  `segments: N` in the header so a compacted session's cost is one number, not a silent split.
- **A GitHub Pages docs site** (`docs/`) — a small multi-page site (nav bar, one page per command)
  embedding real asciinema terminal recordings for every workflow, plus a step-by-step,
  OS-aware install wizard on the homepage.
- **`contrib/homebrew/token-finops-cli.rb`** — a drafted Homebrew formula (installs via a local
  tap today; a published tap is tracked separately).

### Changed

- Consolidated the interim `src/token_finops/` package into
  `token-finops-cli/src/token_finops_cli/`, which is now the single
  package; `token-finops-cli/` itself is kept as a git subtree of the
  original repository so its history is preserved.
- CI moved to `uv`-based `pytest`/`ruff` at the repository root, running
  on Python 3.10–3.13.
- Repository restructured around one root (`README.md`, `AGENTS.md`,
  `docs/`) with the package underneath; original Copilot CLI flags and
  output (`report`, `sessions`, `--budget`, `--cycle-day`, `--watch`,
  `--compact`) are unchanged and still the default when no `--tool` is
  given.

- End-to-end matrix (`tests/test_e2e_matrix.py`): 9 tools × 7 synthetic scenarios through the real
  CLI as a subprocess (adapters, report text/json, sessions, status cache, self-audit dedup, break-even,
  determinism, regeneration). Robustness suite (`tests/test_robustness.py`): garbage/truncated JSONL,
  binary bytes, minimal SQLite schemas, unknown models/fields, odd timestamps, empty/unreadable paths,
  1 MB lines, 200-seed fuzz. Total 812 tests.
- **`docs/INSTALL.md`** — end-user install guide: installing `token-finops` itself (uv tool/pipx/pip,
  PyPI publish pending), plus a Tier 1 / Tier 2 / reference-only rollout for the coding-agent CLIs
  each adapter reads, with macOS (Homebrew-first) and Linux (npm/pip) install commands and auth notes
  for Tier 1 (Claude Code, GitHub Copilot CLI, OpenAI Codex CLI, Gemini CLI, Hermes Agent, Cline/Roo/
  Kilo). No `curl | bash` / `irm | iex` installer is documented anywhere, even where a project ships
  one as its primary method — Hermes Agent is flagged as not yet installable under this policy.
- **`.github/workflows/cli-smoke.yml`** — installs every Tier 1 tool with exactly the command
  documented in `docs/INSTALL.md` (npm on macOS+Linux, Homebrew casks/formulae on macOS, VS Code
  marketplace extensions for Cline/Roo/Kilo) and asserts the binary resolves and answers
  `--version`/`--help`. No authentication, no real telemetry generated — that stays on synthetic
  fixtures. Runs on a weekly schedule plus manual dispatch (external registries, not our own code),
  and on any PR touching itself or `docs/INSTALL.md`. Includes a standing job that fails loudly if
  the deprecated `gemini-cli` Homebrew formula (disable date 2026-12-18) is actually removed.
  `tests/test_cli_smoke_workflow.py` guards the workflow and the doc from silently drifting apart
  (string-level checks, no live network, no new dependency). Extended to Tier 2 (OpenCode, Kilo
  CLI, Aider, Continue.dev): `docs/INSTALL.md` now documents all three (via Haiku sub-agents, each
  claim fact-checked against real sources — one fabricated Kilo CLI Homebrew tap was caught and
  removed before merge), and `cli-smoke.yml` gained a `pipx-cli` job (Aider on Linux) plus matrix
  entries in `npm-cli`/`brew-cli`/`vscode-extension` for the rest.
- **`AUTOCODING.md`** — which CLI/model actually wrote this repo (cloud session vs. local Claude
  Code CLI fan-out), model-assignment rules, and token accounting for each; documents that the
  local-CLI fan-out is currently blocked (the device-bridge `claude` binary is disabled in this
  environment) pending the maintainer running doc tasks from their own terminal instead.
- **`DEVELOPING.md`** — day-to-day dev workflow hub: environment, test subsets (`-k UC-13`, `burn`,
  one adapter, `test_e2e_matrix`, `test_robustness`, `test_cli_smoke_workflow`), working against
  synthetic vs. real telemetry with the full per-tool env-var override table, debugging one
  adapter, the branch-per-task workflow, releasing. Cross-referenced from `AGENTS.md` and
  `CONTRIBUTING.md` so the three docs don't overlap.
- Hermes Agent's official `curl | bash` installer is now documented as the one exception to this
  project's no-`curl | bash` policy (confirmed: no Homebrew tap, apt/deb, AUR, or pip/npm package
  exists for it as of 2026-09-12).
- `claude-tasks.md`: work packages for coding agents on their own branches.
- ruff rule set pinned explicitly in `pyproject.toml` — ruff 0.16 widened its default rule set,
  which broke CI on rules the project had never opted into.
- CI (`.github/workflows/ci.yml`) runs `uv run` against the matrix Python for each job instead of
  whatever interpreter `uv` happened to resolve first, so 3.10–3.13 are each actually exercised.
- `test_cli.py` subprocess invocations now set `PYTHONPATH` explicitly, so they pick up the
  package under test instead of whatever is already installed on `PATH`.

### Fixed
- Adapters no longer abort a scan on non-UTF-8 bytes, directories/unreadable files where transcripts
  are expected, corrupt SQLite stores, drifted record shapes (non-dict payloads, string percentages,
  out-of-range epochs) or TEXT in numeric Copilot columns — the offending source is skipped.
- Codex synthetic rollouts now carry their own mtime, so `quota()` picks the newest day.

- Bedrock-style Claude model identifiers (e.g. region/vendor-prefixed IDs)
  were not normalising to their plain model name, so `self-audit`'s
  by-model table under-reported one model and over-reported another.
- Non-object pricing override files (e.g. a bare number instead of an
  `{"input": ..., "output": ...}` mapping) crashed pricing lookup instead
  of being rejected or ignored cleanly.
- `report --json` could emit `Infinity` for an unbounded runway, which is
  not valid JSON; unbounded runways now serialise as `null`
  (see `cli.py::_finite`).
- `token-finops synth` crashed on regeneration into an existing output
  directory instead of overwriting cleanly.

## [0.2.0] and earlier

Predates this repository's restructuring. See the original repository:
[oh-my-agent-code/token-finops-cli](https://github.com/oh-my-agent-code/token-finops-cli).
