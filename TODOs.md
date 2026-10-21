# TODOs — what's next

A short, human-facing "what's outstanding" list. For the detailed agent-ready work packages
(branch names, acceptance criteria, model hints) see `claude-tasks.md`.

## Done this session

- [x] Colorized statusline (ANSI green/yellow/red at 75%/90%, bold model name) — committed `5b940f0`.
- [x] `docs/casts/06-install-pip.cast` + `docs/index.html` GitHub Pages landing page, live at
  https://qvest-ssels.github.io/burn-token-burn/ — committed `563b9f8`, fixed up in `4bfe0ec`
  (starts on `pip install`, no leaked `/tmp` path, single-tool example scoped to whatever's
  configured via the statusLine hook instead of an all-adapters comparison).
- [x] Homebrew formula draft at `contrib/homebrew/token-finops-cli.rb` — committed `77bae41`,
  installed/tested/uninstalled locally via a throwaway tap. Still needs a real tap repo to be
  user-installable (see below).

## Done this session (Claude Sonnet 5, cloud session)

- [x] **Statusline: bring back the `report --compact` hash progress bar** — `collect-statusline`
  now renders `progress_bar()` per window (10-wide, narrower than `report`'s 30 since it shares a
  line with other segments) instead of a bare percentage, e.g.
  `claude-sonnet-5 | 5h [####------]  40.0% | 7d [#---------]  12.0%`, still colour-coded at the
  same 75 %/90 % thresholds — `docs/TMUX.md` updated.
- [x] **Statusline: optional sub-agent count + token summary** — opt-in via
  `~/.token-finops/config.json` (`{"statusline": {"show_subagents": true}}`, off by default —
  parses `subagents/agent-*.jsonl` on every refresh, extra disk I/O not everyone wants); reuses
  `report.summarize()` over the sibling `<session>/subagents/` directory derived from Claude
  Code's `transcript_path` payload field. Appends `2 agents · 8.4k tokens` to the line. 5 new
  tests. Branch `feature/agentic/statusline-enhancements`, see `AGENTIC.md`.
- [x] **T-02 Copilot synth scale rebalance** — `synth --scenario steady` + `report --budget 1500`
  now reads 22.5% OK, `--scenario exhausted` reads 100% OUT, matching a real Copilot Pro
  allowance instead of the old ~900 AIU/request scale that blew past even Max's 20,000 AIU
  allowance in two weeks. See `claude-tasks.md`'s Done section for the full detail. Branch
  `feature/agentic/copilot-synth-scale`, see `AGENTIC.md`.
- [x] Scroll-triggered asciinema autoplay + 4-step homepage install wizard (PR #8) -- see
  `AGENTIC.md`.

## Open

- [x] **`test_since_map` flake — root-caused and fixed.** Not random ordering (`pytest-randomly`
  isn't even installed): `REAL_NOW` was a module-level constant captured once at collection time,
  and on a 100+s full-suite run the test could execute well over its 5s tolerance later, failing
  on nothing but elapsed wall-clock time. Fixed by comparing against a `now` taken at assertion
  time instead. Shipped directly to `oh-my-agent-code/token-finops-cli` (PR #6, released in
  v0.5.0 2026-10-19) rather than through this monorepo's `token-finops-cli/` subtree.

- [ ] **Recurring public CO2-estimate data as a "know-how" service** — instead of a one-time
  static CO2 research page, periodically re-run the CO2/energy estimate (via a scheduled GitHub
  Actions workflow, same cron pattern as `pypi-smoke.yml`/`homebrew-smoke.yml`) and publish the
  refreshed numbers to the docs site as a standing public-service page — framed as ongoing
  research/tracking, not just a one-off blog post. Needs: (a) the actual CO2 research page to
  exist first (currently a placeholder pointing at `docs/CO2_ESTIMATE.md` — see the
  `docs-refresh-and-co2-page` branch/PR), (b) a decision on what "periodically re-run" even means
  here, since the underlying inputs (grid-mix gCO2/kWh, cloud PUE, energy-per-token estimates)
  are slow-moving published figures re-sourced by hand, not something with a live API to poll —
  likely means "re-check sources quarterly and bump `docs/sources.md`'s review dates," not a fully
  automated pipeline. Explicitly parked — human said "the co2 can stay just dont continue atm" on
  2026-09-18, so no active work until picked back up.

- [ ] **New GitHub Pages subpage: Qwen Coder via Ollama, as a local sub-agent model** — write a
  docs subpage (`docs/qwen-ollama.md` or `.html`, linked from `docs/index.html`) covering
  installing Ollama on macOS and pulling a Qwen Coder model, then actually try it end-to-end in a
  local session on this Mac: install Ollama, pull the model, and validate it can serve as a
  sub-agent backend so future sessions can route menial/high-volume sub-agent work to a free local
  model instead of burning Anthropic tokens. Needs a design answer before the doc can be honest:
  Claude Code sub-agents run on Anthropic models within the same session — there's no built-in
  "route this sub-agent to a local Ollama model" mechanism, so this would need either (a) an MCP
  server that proxies tool calls to a local Ollama endpoint, or (b) a separate harness/CLI outside
  Claude Code entirely that only *this* project's docs point people at. Don't write the page until
  that's resolved, or it'll document something that doesn't work. Multi-GB model pull — do this as
  its own scoped session, not opportunistically.
- [ ] **Homebrew tap repo** — `contrib/homebrew/token-finops-cli.rb` only installs today via a
  local throwaway tap; a real `qvest-ssels/homebrew-token-finops` tap repo (or homebrew-core
  submission once the project has more history) is needed for `brew install token-finops-cli` to
  work for anyone else.

- [ ] **UX persona pass: `docs/USER-JOURNEYS.md`** — a Fable-model agent writes first-time-user vs.
  power-user journey concepts (what to show/explain first, where each persona currently bounces or
  gets confused, what "level 2" content power users go digging for). Feeds a follow-up Sonnet
  implementation pass that applies whatever Fable recommends to the docs site (nav ordering,
  content placement, homepage vs. sub-page split). Runs after the multi-page docs restructuring
  (`feature/agentic/docs-multipage-nav`) lands, since the journey doc should describe the real
  current structure, not the old single-page one.

## Remote / release housekeeping

- [x] **PyPI trusted publishing + release** — resolved: the real, already-working trusted
  publisher lives on the separate standalone `oh-my-agent-code/token-finops-cli` repo (not
  `tronicum/burn-token-burn`, which never had one). v0.3.0 (2026-09-14), v0.4.0 (2026-09-24,
  merged after external review — security fix, see `oh-my-agent-code/token-finops-cli#2`), and
  v0.5.0 (2026-10-19 — `--window 5h|7d` for Claude Code/Codex, `--version`/`-V`/`version`) have
  all shipped from there. See `claude-tasks.md`'s T-05 entry for the subtree-split-era detail,
  including the `.github/workflows/` gotcha found along the way.

- [ ] **This monorepo's `token-finops-cli/` subtree is stale at 0.4.0** — the v0.5.0 work
  (`--window`, `--version`, the `test_since_map` fix) was built and merged directly against
  `oh-my-agent-code/token-finops-cli` (PRs #6/#7/#8), bypassing this repo's subtree-split release
  flow entirely. `token-finops-cli/pyproject.toml` here still says `0.4.0` and is missing all
  three changes. Needs a decision: either stop treating this monorepo's subtree as the source of
  truth and pull changes *back* from the package repo periodically, or go back to shipping
  package-level work through the subtree-split flow and stop PRing oh-my-agent-code directly.
  Whichever is chosen, the current state (two diverging checkouts of the same package) should not
  persist.

## From the existing backlog (`claude-tasks.md`) — remaining

- [ ] T-07 Quality-tier mapping from Artificial Analysis
- [ ] T-13 re-record casts on each release (now 6 casts, not 5) — gate on 0.4.0 wheel being live
  on PyPI
- [ ] T-14 PRs to awesome-lists — text prepared, not submitted (external-repo action, needs
  explicit human go-ahead)

T-03, T-04, T-08/T-09/T-10, T-11, T-12, T-15, T-16, and the budget-check GitHub Action are done —
see `claude-tasks.md`'s Done section. See `claude-tasks.md` for full acceptance criteria and
branch names on remaining items.
