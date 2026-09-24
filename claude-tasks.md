# claude-tasks.md — work packages for Claude Code (or any coding agent) on this repo

How to use: pick ONE task, create the branch named in it from `main`, do the work, run
`cd token-finops-cli && uv run pytest -q && uv run ruff check src tests`, run
`uv run token-finops self-audit` and paste the by-model table into the PR description, open a PR
against `main`. Never commit to `main` directly. Rules: `AGENTS.md`. Model hint per task is a
suggestion — menial work on Sonnet/Haiku, judgement-heavy work on Opus. Tick the box in this file
in the same PR.

Remote: `origin = https://github.com/qvest-ssels/burn-token-burn.git` (leading fork, branch
`main`); `upstream = https://github.com/tronicum/burn-token-burn.git` (original). Agentic work
follows `AGENTS.md`'s branch + PR rule — see `AGENTIC.md` before claiming a task.

## Ready now

- [x] **T-03 `--online` quota fetchers** — branch `feature/agentic/online-quota-fetchers` — model: Opus — M — done:
  all four fetchers shipped in `token_finops_cli/online.py` (stdlib `urllib` only), `--online` added to
  `report` and `status` (off by default; on `status` it implies a rescan, since the `last.json` cache was
  built with the previous run's quota source). A successful fetch promotes that run's `source_of_truth`
  from `local_sum` to `hybrid` so the provider's number decides used% while local events still drive the
  burn rate. Every failure path — no flag, no credential, no network, 429, non-JSON, drifted shape —
  returns to the offline path silently; verified by diffing a real `--online` run behind a refused
  connection against the plain offline run (byte-identical, exit 0). Responses *and* failures are cached
  180 s. `tests/test_online.py` stubs `urllib.request.urlopen`, and an autouse `no_network` guard in
  `conftest.py` makes any un-stubbed call raise a `BaseException` (so `online_quota`'s fail-closed
  `except Exception` cannot hide a real request) for the whole suite.
  Original spec: optional live quota, never on by default, each behind its ADR note, cached ≥ 180 s in
  `~/.token-finops/online-cache.json`, hard-fail closed to the offline path on any error:
  Copilot `GET https://api.github.com/copilot_internal/user` (token from `gh auth token` or
  `GITHUB_TOKEN`); Anthropic `GET https://api.anthropic.com/api/oauth/usage` (header
  `anthropic-beta: oauth-2025-04-20`, token from `~/.claude/.credentials.json`; expect 429s);
  Gemini `POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota`; OpenRouter
  `GET https://openrouter.ai/api/v1/key` for Hermes. Add `--online` to `report`/`status`; unit-test
  with a stubbed `urllib` (no network in CI). Update ADRs 0001/0002/0004/0005 and `docs/sources.md`.

- [x] **T-04 Claude Code `/runway` skill** — branch `feature/agentic/claude-code-runway-skill` — model: Opus — S
  Shipped `contrib/claude-code/runway/SKILL.md` (a skill is a *directory* with `SKILL.md`, not a
  flat file) and `contrib/codex/prompts/runway.md` (Codex custom prompt, `/prompts:runway`);
  both run `token-finops status --format plain` + `report --tool claude_code|codex --compact` and
  tell the agent to size the fan-out to the runway. Install docs per scope in each `README.md`;
  `tests/test_contrib_skills.py` feeds every command string through `shlex.split()` and the real
  argparse parser, so a flag the CLI does not have fails CI. Codex's newer "skills" successor is
  documented-but-unstable, so only the verifiable prompt form shipped (`docs/INTEGRATIONS.md` §3).

- [ ] **T-05 PyPI trusted publishing + v0.3.0 release** — branch `release/0.3.0` — model: Sonnet — S
  Verify `.github/workflows/release.yml` works from the `token-finops-cli/` subdirectory (artifact
  paths), add a `CHANGELOG.md` link check, bump nothing (already 0.3.0). Human step: configure PyPI
  trusted publisher for `tronicum/burn-token-burn` → project `token-finops-cli`, then
  `git tag v0.3.0 && git push --tags`. Acceptance: dry-run `uv build` in CI on the PR.

- [ ] **T-07 Quality-tier mapping from Artificial Analysis** — branch `savings/quality-tiers` — model: Opus — M
  `hardware_profiles.json` assigns `quality_tier` (haiku/sonnet/opus) by hand. Fetch the
  Artificial Analysis intelligence index for the listed open models, store index values with a date
  in the JSON, derive the tier from index bands, document the bands in `docs/guide/04`. Keep the
  "it's an assumption" caveat. **Deferred until after T-11** (2026-09-22).

  Partial research from a paused 2026-09-22 attempt, saved so the lookup isn't redone from scratch:
  - Use **Artificial Analysis Intelligence Index v4.3.2** (as of 2026-09-22) — a much harsher scale
    than older v3-era scores (current leader GPT-5.6 Sol ~58.9, Claude Fable 5.1 ~53). Don't mix
    v3/v4 numbers when deriving band cutoffs.
  - Confirmed v4.3.2 values so far: `gpt-oss-120b` (high) = 12, `llama-3-3-instruct-70b` = 8
    (AA-flagged as *estimated*), `qwen3-6-27b` (Reasoning) = 21.
  - Still missing: Qwen3 8B, Qwen3 32B, Qwen3 235B-A22B, and clean v4.3.2 figures for
    current-gen Claude Haiku/Sonnet/Opus as calibration anchors (search snippets returned a mix of
    index versions and AA-flagged estimates — verify against per-model or comparison pages).
  - Working retrieval trick: `artificialanalysis.ai/models/comparisons/<slug-a>-vs-<slug-b>` pages
    render real numeric scores + index version; the main `/models` leaderboard doesn't survive
    markdown conversion. `qwen3-32b-reasoning` 404s as a slug — the real Qwen slugs need discovery
    first (site map or domain-restricted search).
  - Heads up for whoever picks this up: `llama-3-3-instruct-70b` (8) scoring *below*
    `gpt-oss-120b` (12) while both are currently hand-assigned `sonnet`-tier suggests a literal
    index-derived mapping will demote at least one model — the user-visible `savings`/
    `cost-per-token` behavior change the original spec asks to flag.

- [x] **T-15 self-audit across compaction** — branch `fix/self-audit-compaction` — model: Sonnet — S
  When Claude Code compacts context it starts a new transcript for the same session id (and Cowork
  cloud sessions do the same). `self-audit --session X` currently sees only the newest transcript;
  the dogfooding run split into $224.95 + $56.63. Stitch every transcript sharing the session id
  (main + `subagents/`), dedup across them, and print "segments: N" in the header. Fixture: two
  JSONL files with the same `sessionId` in `tests/`. Acceptance: totals equal the sum of the parts.

- [x] **T-16 Claude Desktop / Cowork (macOS) coverage** — branch `feature/agentic/adr-0013-claude-desktop` — model: Opus — S — done: [ADR-0013](docs/adr/0013-claude-desktop-cowork.md). Findings differ from the premise in two ways: Desktop caches the account-wide 5 h/7 d utilisation offline in `plan-usage-history.json` (~30 days of history), and on-computer Cowork mirrors full token/USD/quota records to the Mac in `local-agent-mode-sessions/**/audit.jsonl`. Cloud Cowork confirmed metadata-only. Follow-ups: quota source + on-computer Cowork adapter.
  Question from the field: "can we measure Claude Desktop?" Investigate and write ADR-0013:
  the desktop chat app keeps no local usage telemetry (conversations are server-side; check
  `~/Library/Application Support/Claude/` for anything usable and document what is there);
  Cowork cloud sessions leave their transcripts in the sandbox, not on the Mac, so `self-audit`
  must run *inside* the session (as this repo did) and export JSON into the repo; on-computer
  Cowork runs in a local VM — check whether its transcripts are reachable. The only account-wide
  number across Desktop + Code + Cowork is the OAuth usage percentage (T-03 `--online`), and the
  macOS menu-bar surface is already `status --format xbar` (SwiftBar). Verdict tier: reference-only
  or usage-via-online. Add a row to README and `docs/landscape.md`.

## Next

- [x] **T-08 Neovim plugin `token-finops.nvim`** — branch `feature/agentic/nvim-plugin` — model: Sonnet — M —
  done: `contrib/nvim/token-finops.nvim/` — Lua module reads `~/.token-finops/last.json` (never
  rescans), lualine component (`require("token-finops").statusline()`; heirline gets a one-line
  snippet in the README since it just wants the same function), `:TokenFinops` floating window
  with the per-tool table, `:checkhealth token-finops`. Verified with `luac -p` on every file and a
  headless `nvim --headless` smoke script (`test/smoke.lua`) against a synthetic fixture, including
  missing/corrupt/wrong-`schema_version` cache paths.

- [x] **T-09 VS Code status-bar extension** — branch `feature/agentic/vscode-extension` — model: Sonnet — M
  Shipped `contrib/vscode/` as a standalone extension (`package.json`, `extension.js`): status-bar
  item reads `~/.token-finops/last.json` directly on a 45s timer (no process-spawn per tick, same
  pattern as `contrib/tmux`/`contrib/nvim`), click → detail webview rendering the full per-tool
  table; a rate-limited "Refresh Now" command shells out `token-finops status --fresh` on demand.
  Plain JavaScript, not TypeScript (no build step needed to run via Extension Development Host —
  see the README's "Why plain JavaScript" section). `node`/`npm` were available but packaging
  (`@vscode/vsce`) and Marketplace publishing were not attempted without asking first, so the
  extension is unverified in a real VS Code instance — see `contrib/vscode/README.md` for the
  "Verification status" note.

- [x] **T-10 Emacs `token-finops.el`** — branch `feature/agentic/emacs-plugin` — model: Sonnet — S
  Mode-line segment + transient buffer over the cache file. Shipped as `contrib/emacs/`.

- [ ] **T-11 Desktop notifications at WARN/CRIT** — branch `feat/notify` — model: Sonnet — S
  `token-finops status --notify` → `notify-send` / `terminal-notifier` / PowerShell toast when the
  binding constraint changes class; state in `~/.token-finops/notify-state.json`.

- [ ] **T-12 Prometheus textfile exporter** — branch `feat/prometheus` — model: Sonnet — S
  `status --format prometheus` writing `token_finops_used_fraction{tool=…}`,
  `token_finops_runway_days{tool=…}` for node_exporter's textfile collector.

- [ ] **T-13 Re-record asciinema casts on release** — branch `docs/casts-0.3.0` — model: Haiku — S
  Follow `docs/casts/README.md`; upload to asciinema.org and link from README.

- [ ] **T-14 PRs to the two awesome-lists** — model: Sonnet — S (no branch here)
  Add `token-finops-cli` to QuesmaOrg/awesome-ai-tokenomics (Monitor → Dashboards) and
  pleasedodisturb/awesome-llm-token-optimization (Cost Tracking Tools). One line each, follow their
  contribution rules.

## Parked (needs a decision first)

- **Cursor adapter** — ADR-0008 says reference-only because local `tokenCount` is unreliable. Revisit only
  if Cursor documents a stable local usage store.
- **Ollama logging proxy** — ADR-0012; a separate small tool, not part of this package.
- **Windsurf** — ADR-0011; no local data.

## Done (keep for history)

- [x] **T-02 Copilot synth scale** — `build_synthetic_db`'s per-event `total_nano_aiu` rescaled
  from ~900 AIU/request (~300x too hot -- a real account averages ~1.5 AIU/request) to ~3
  AIU/request, so `synth --scenario steady` now reads sensibly against real plan sizes: 22.5% of
  a Copilot Pro allowance (1500) over the default 14-day window, `OK`; `--scenario exhausted`
  (per-event multiplier raised 25x -> 100x, to comfortably clear even Max's 20,000 AIU allowance
  regardless of how many synthetic days the real calendar-month window happens to cover) ->
  `EXHAUSTED`. `DEFAULT_BUDGET_AIU` (used when `report`/`status` get no `--budget`) rescaled
  50,000 -> 20,000 (Max, the largest real individual plan -- the old default was bigger than
  every real plan and so never flagged tight usage). Removed the `--budget 500000`-style
  workarounds from `tests/test_e2e_matrix.py` (now `--budget 1500`, verified empirically robust
  across every day-of-month for the fixed seed, accounting for `compute_runway`'s pace-based
  CRITICAL rule) and `tests/test_usecases.py`'s UC-45..49 (now `--budget 1500`, deterministic
  since those fix `now`); regenerated `docs/USECASES.md`, updated `docs/SYNTH.md`. 817 passed, 1
  skipped, ruff clean. Branch `feature/agentic/copilot-synth-scale`, see `AGENTIC.md` — 2026-09-15

- [x] **T-20 Tier 2 CI install-smoke coverage** — reconciled: this was already implemented
  directly on main in the same batch as `docs/INSTALL.md` Tier 2 (not delegated to a branch/PR
  as the task described) — `.github/workflows/cli-smoke.yml` has OpenCode/Kilo CLI (npm-cli),
  OpenCode/Aider (brew-cli), Aider (pipx-cli), Continue.dev (vscode-extension: `Continue.continue`,
  JetBrains 22707 skipped/documented) — confirmed present 2026-09-12, no further work needed.

- [x] **`token-finops cost-per-token`** — new subcommand, $/1M tokens per tool/model:
  real list price + realized blended rate for every pay-per-token adapter; for
  Copilot (AI credits + per-model request multiplier, no official $/token rate)
  a clearly labelled *derived* ratio instead, never conflated with a real price.
  `docs/COST_PER_TOKEN.md` added, cross-referenced from `docs/README.md` and
  `README.md`. 10 new tests (812 passed, 1 skipped), ruff clean — 2026-09-12

- [x] **T-17 `burn --by` partial periods** — `hist.period_days` returned the full calendar length
  of a week/month even when the reporting window only covered part of it (the first/last period
  of a `--since`/`--by` window), understating `usd_per_30d`/`maxing` at the edges. Added
  `hist.period_bounds()` and `hist.period_window_days()`; `hist.group()` now attaches
  `period_days` (actual days of the period inside `[min(days), max(days)]`, not the calendar
  length) and `partial` to each group, and `burn_report`/`render_burn` normalise by that and mark
  partial periods with a trailing `*` plus a one-line legend. Updated
  `test_burn_report_by_week_periods` / `..._by_month_without_plan_has_no_maxing` /
  `..._merges_history_rows` (they exercised the old, understated calendar-days denominator on a
  partial window) and `docs/BURN.md`; added full-period and 3-of-7-day partial-week tests — 802
  passed, 1 skipped — 2026-09-12

- [x] Phase 0–3 of `docs/PLAN.md`, 9 adapters, runway engine, `status` renderer + cache, synth
  generator, 50 use cases, e2e matrix + robustness suite (704 tests) — 2026-09-05…09
- [x] `burn` subcommand (maxing multiplier, weekly/monthly tables, history, efficiency, prepaid
  rate/discount); CI fix (ruff rule pin, matrix python, PYTHONPATH); `docs/INSTALL.md` (Tier 1);
  T-18 done directly on main (user-directed, not delegated) as `.github/workflows/cli-smoke.yml`
  + `tests/test_cli_smoke_workflow.py` (doc/workflow drift guard, no live network) — 787 tests —
  2026-09-11…12
- [x] `AUTOCODING.md` (which CLI/model wrote this repo, model assignment, local-CLI fan-out
  accounting — local fan-out attempted but blocked: the device-bridge `claude` binary is disabled
  in this environment, see AUTOCODING.md); Hermes Agent's `curl|bash` documented as the one
  install-policy exception (no other packaging exists); `DEVELOPING.md` (day-to-day dev workflow
  hub, cross-referenced from AGENTS.md/CONTRIBUTING.md); T-19 done directly on main via three
  Haiku sub-agents (one per tool, sequential edits to `docs/INSTALL.md`), each fact-checked
  afterward — one fabricated command caught and fixed (Kilo CLI has no Homebrew tap; the
  sub-agent invented `Kilo-Org/tap/kilo`) — 2026-09-12
- [x] **T-06 Fraunhofer ISE LCOE citation** — `savings/energy.json` `solar-de-lcoe` updated to
  0.104 EUR/kWh (10.4 ct/kWh, midpoint of the 6.3–14.4 ct/kWh small rooftop PV ≤30 kWp range),
  cited to Fraunhofer ISE "Levelized Cost of Electricity – Renewable Energy Technologies" (July
  2024, the current edition); `docs/sources.md` and `docs/guide/04-local-vs-cloud.md` updated to
  match (old placeholder was 8–12 ct/kWh estimate, "primary Fraunhofer ISE figure still to be
  cited") — 2026-09-12
- [x] **T-01 ADR hardening notes** — added "Robustness" paragraphs to Consequences sections of ADRs
  0001–0007, 0009, 0010 describing what each adapter tolerates (non-UTF-8 bytes, garbage in JSONL,
  corrupt SQLite, drifted record shapes, missing columns, unparsable timestamps, unknown models);
  ruff and pytest pass (787 passed, 1 skipped) — 2026-09-12
