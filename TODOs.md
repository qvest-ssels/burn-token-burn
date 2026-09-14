# TODOs — what's next

A short, human-facing "what's outstanding" list. For the detailed agent-ready work packages
(branch names, acceptance criteria, model hints) see `claude-tasks.md`.

## In flight / uncommitted

- [ ] **Commit the colorized statusline change** — `token-finops-cli/src/token_finops_cli/cli.py`
  (`cmd_collect_statusline`) and `tests/test_statusline.py` have uncommitted changes: ANSI colour
  (green/yellow/red at the 75%/90% thresholds) plus a bold model name. 813 tests pass locally.
  Needs a commit + push to `origin` (qvest-ssels/burn-token-burn).
- [ ] **Ascii-theater docs page** — background agent recording `docs/casts/06-install-pip.cast`
  (real `pip install token-finops-cli` from PyPI) and building `docs/index.html` with an embedded
  asciinema-player for all 6 casts, then enabling GitHub Pages on `qvest-ssels/burn-token-burn`
  (source: `main` / `/docs`). Check the agent's final report for the Pages URL and commit hash.
- [ ] **Homebrew cask/formula for `token-finops-cli`** — requested, not started. Likely a formula
  (it's a Python CLI, not a GUI app — cask is for macOS apps) via `pip`/`pipx`-based install or a
  PyOxidizer/pex-built binary; needs a tap (e.g. `qvest-ssels/homebrew-token-finops`) since this
  isn't going into homebrew-core without history/notability.

- [ ] **Statusline: optional sub-agent count + token summary** — `cmd_collect_statusline` currently
  only reads `model`/`rate_limits`/`cost` from the piped JSON; it ignores `session_id`/
  `transcript_path`, which Claude Code's real statusLine payload includes. Opt-in (new
  `~/.token-finops/config.json`, doesn't exist yet) feature: parse the session's
  `subagents/agent-*.jsonl` files and append something like `3 agents · 142.8k tokens` to the
  line, reusing the existing `summarize()` per-agent token/cost totals already used by
  `self-audit` (`cli.py:211-226`) — no new aggregation math needed, just wiring it into the
  statusline hook and gating it behind the config flag since it adds disk I/O per refresh.

- [ ] **Statusline: bring back the `report --compact` hash progress bar** — `report.py`'s
  `progress_bar()`/`compact_line()` (`report.py:39,94`) render the `[####------] 92.0%  runway
  3.5h  OK` style line already used by `report --compact` for Copilot etc., but `collect-statusline`
  currently only prints `model | 5h 37% | 7d 12%` with no bar at all. Wire `progress_bar()` into
  `cmd_collect_statusline` so the live Claude Code statusline shows the same hash-bar summary
  (through to runway/status) instead of just the bare percentages.

## Remote / release housekeeping

- [ ] **Reconfigure PyPI trusted publishing for the new repo.** `.github/workflows/release.yml`
  uses OIDC trusted publishing tied to `owner/repo/workflow`. Now that `origin` is
  `qvest-ssels/burn-token-burn` (see below), releasing from there requires registering a new
  trusted publisher on the PyPI project settings for `token-finops-cli` — this is a PyPI-side
  change only a project owner can make, not scriptable from here.
- [ ] **Decide the release path**: tag `v0.3.x` from `qvest-ssels/burn-token-burn` once trusted
  publishing is reconfigured, or keep releasing from `upstream` (tronicum/burn-token-burn) and use
  qvest-ssels purely as a mirror/fork. Current state: `origin` = qvest-ssels (primary, just
  created, only `main` pushed, no tags), `upstream` = tronicum (original, has the real PyPI
  release history).
- [ ] **T-05 PyPI trusted publishing + release** (from `claude-tasks.md`) — still open regardless
  of which repo ends up as the release source.

## From the existing backlog (`claude-tasks.md`) — top picks

- [ ] T-02 Copilot synth scale rebalance
- [ ] T-03 `--online` live quota fetchers (Copilot/Anthropic/Gemini/OpenRouter)
- [ ] T-04 Claude Code `/runway` skill
- [ ] T-07 Quality-tier mapping from Artificial Analysis
- [ ] T-15 self-audit across context-compaction boundaries
- [ ] T-16 Claude Desktop / Cowork coverage doc
- [ ] T-08/T-09/T-10 editor integrations (Neovim, VS Code, Emacs)
- [ ] T-11 desktop notifications, T-12 Prometheus exporter
- [ ] T-13 re-record casts on each release (now 6 casts, not 5)
- [ ] T-14 PRs to awesome-lists

See `claude-tasks.md` for full acceptance criteria and branch names on each.
