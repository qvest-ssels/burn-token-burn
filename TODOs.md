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

## Open

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
