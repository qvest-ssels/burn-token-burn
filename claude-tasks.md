# claude-tasks.md — work packages for Claude Code (or any coding agent) on this repo

How to use: pick ONE task, create the branch named in it from `main`, do the work, run
`cd token-finops-cli && uv run pytest -q && uv run ruff check src tests`, run
`uv run token-finops self-audit` and paste the by-model table into the PR description, open a PR
against `main`. Never commit to `main` directly. Rules: `AGENTS.md`. Model hint per task is a
suggestion — menial work on Sonnet/Haiku, judgement-heavy work on Opus. Tick the box in this file
in the same PR.

Remote: `origin = https://github.com/tronicum/burn-token-burn.git` (branch `main`).

## Ready now

- [ ] **T-01 ADR hardening notes** — branch `adr/robustness-notes` — model: Haiku/Sonnet — S
  `tests/test_robustness.py` hardened every adapter (non-UTF-8 bytes, directories where files are
  expected, corrupt SQLite, drifted record shapes, absurd epochs). Add a short "Robustness" line to
  the *Consequences* section of ADRs 0001–0007, 0009, 0010 describing what the adapter now tolerates
  and what it silently skips. Acceptance: each ADR mentions skip-on-error behaviour; `docs/adr/README.md`
  table unchanged.

- [ ] **T-02 Copilot synth scale** — branch `synth/copilot-aiu-scale` — model: Sonnet — S
  `build_synthetic_db` bills ~900 AI units per request (≈ $9/req), so a 14-day "steady" home is
  EXHAUSTED against a Pro allowance (1500). Rescale `total_nano_aiu` so steady ≈ 40–60 % of 1500
  over a month, exhausted > 100 %, burst visible in the EMA. Update tests that hard-code the old
  scale (`tests/test_e2e_matrix.py` passes `--budget 500000` as a workaround — remove that).
  Acceptance: `token-finops synth --scenario steady` + `report --budget 1500` → OK; exhausted → EXHAUSTED.

- [ ] **T-03 `--online` quota fetchers** — branch `feat/online-quota` — model: Opus for design, Sonnet for code — M
  Optional live quota, never on by default, each behind its ADR note, cached ≥ 180 s in
  `~/.token-finops/online-cache.json`, hard-fail closed to the offline path on any error:
  Copilot `GET https://api.github.com/copilot_internal/user` (token from `gh auth token` or
  `GITHUB_TOKEN`); Anthropic `GET https://api.anthropic.com/api/oauth/usage` (header
  `anthropic-beta: oauth-2025-04-20`, token from `~/.claude/.credentials.json`; expect 429s);
  Gemini `POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota`; OpenRouter
  `GET https://openrouter.ai/api/v1/key` for Hermes. Add `--online` to `report`/`status`; unit-test
  with a stubbed `urllib` (no network in CI). Update ADRs 0001/0002/0004/0005 and `docs/sources.md`.

- [ ] **T-04 Claude Code `/runway` skill** — branch `feat/claude-code-skill` — model: Sonnet — S
  A skill/slash command file under `contrib/claude-code/` that runs `token-finops status --format plain`
  and `report --tool claude_code` and tells the agent to *check runway before spawning sub-agents*
  (`docs/INTEGRATIONS.md` §3). Include install instructions and a smoke test that the command
  string parses. Same for Codex (`contrib/codex/`) if its custom-command format is verifiable.

- [ ] **T-05 PyPI trusted publishing + v0.3.0 release** — branch `release/0.3.0` — model: Sonnet — S
  Verify `.github/workflows/release.yml` works from the `token-finops-cli/` subdirectory (artifact
  paths), add a `CHANGELOG.md` link check, bump nothing (already 0.3.0). Human step: configure PyPI
  trusted publisher for `tronicum/burn-token-burn` → project `token-finops-cli`, then
  `git tag v0.3.0 && git push --tags`. Acceptance: dry-run `uv build` in CI on the PR.

- [ ] **T-06 Fraunhofer ISE LCOE citation** — branch `docs/lcoe-source` — model: Sonnet — S
  `savings/energy.json` `solar-de-lcoe` is an estimate. Find the current Fraunhofer ISE
  "Stromgestehungskosten" residential PV range, set the value, cite it in `docs/sources.md`
  with review date, adjust `docs/guide/04-local-vs-cloud.md` if the number moved.

- [ ] **T-07 Quality-tier mapping from Artificial Analysis** — branch `savings/quality-tiers` — model: Opus — M
  `hardware_profiles.json` assigns `quality_tier` (haiku/sonnet/opus) by hand. Fetch the
  Artificial Analysis intelligence index for the listed open models, store index values with a date
  in the JSON, derive the tier from index bands, document the bands in `docs/guide/04`. Keep the
  "it's an assumption" caveat.

- [ ] **T-15 self-audit across compaction** — branch `fix/self-audit-compaction` — model: Sonnet — S
  When Claude Code compacts context it starts a new transcript for the same session id (and Cowork
  cloud sessions do the same). `self-audit --session X` currently sees only the newest transcript;
  the dogfooding run split into $224.95 + $56.63. Stitch every transcript sharing the session id
  (main + `subagents/`), dedup across them, and print "segments: N" in the header. Fixture: two
  JSONL files with the same `sessionId` in `tests/`. Acceptance: totals equal the sum of the parts.

- [ ] **T-16 Claude Desktop / Cowork (macOS) coverage** — branch `docs/adr-0013-claude-desktop` — model: Opus — S
  Question from the field: "can we measure Claude Desktop?" Investigate and write ADR-0013:
  the desktop chat app keeps no local usage telemetry (conversations are server-side; check
  `~/Library/Application Support/Claude/` for anything usable and document what is there);
  Cowork cloud sessions leave their transcripts in the sandbox, not on the Mac, so `self-audit`
  must run *inside* the session (as this repo did) and export JSON into the repo; on-computer
  Cowork runs in a local VM — check whether its transcripts are reachable. The only account-wide
  number across Desktop + Code + Cowork is the OAuth usage percentage (T-03 `--online`), and the
  macOS menu-bar surface is already `status --format xbar` (SwiftBar). Verdict tier: reference-only
  or usage-via-online. Add a row to README and `docs/landscape.md`.

- [ ] **T-17 `burn --by` partial periods** — branch `fix/burn-partial-periods` — model: Sonnet — S
  `hist.period_days` returns the calendar length (7 / 28–31) even when the window only covers part
  of the first/last period, so `/30d $` and `maxing` are understated at the edges. Normalise by the
  days actually inside the window (min(period end, last day) − max(period start, first day) + 1) and
  mark partial periods with `*`. Tests in `tests/test_burn_history.py`.

## Next

- [ ] **T-08 Neovim plugin `token-finops.nvim`** — branch `feat/nvim` — model: Sonnet — M
  Lua module reading `~/.token-finops/last.json` (never runs a rescan), lualine/heirline component,
  `:TokenFinops` floating window with the per-tool table, health check. `docs/INTEGRATIONS.md` §2.

- [ ] **T-09 VS Code status-bar extension** — branch `feat/vscode` — model: Sonnet — M
  Status-bar item from `status --format json`, click → detail webview; ships under `contrib/vscode/`
  with its own package.json; reaches the Cline/Roo/Kilo audience (ADR-0007).

- [ ] **T-10 Emacs `token-finops.el`** — branch `feat/emacs` — model: Sonnet — S
  Mode-line segment + transient buffer over the cache file.

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

- [x] Phase 0–3 of `docs/PLAN.md`, 9 adapters, runway engine, `status` renderer + cache, synth
  generator, 50 use cases, e2e matrix + robustness suite (704 tests) — 2026-09-05…09
