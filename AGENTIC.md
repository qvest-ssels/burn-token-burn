# AGENTIC.md — who's working on what

Coordination log for concurrent coding-agent sessions on this repo (see `AGENTS.md`'s
"branch + PR, not direct-to-main" rule). More than one agentic session can be active at
once; this file is how they avoid picking the same task or clobbering each other's branch.

**Before starting agentic work:** check the table below for an `in progress` row that
overlaps the files/topic you're about to touch. If nothing overlaps, add a row for
yourself (branch, task, files you expect to touch, status `in progress`), do the work on
that branch, then flip status to `done` (or `PR opened` / `merged`) and link the PR. Don't
delete old rows — move them to "Done" below instead, so the history stays legible.

## In progress / open

| Session | Branch | Task | Touches | Status |
|---|---|---|---|---|

## Done

| Session | Branch | Task | Touches | Status |
|---|---|---|---|---|
| Claude Opus 5 (local) | `feature/agentic/shell-completions` | Static bash/zsh/fish tab-completion scripts for `token-finops` (subcommand + per-subcommand flag + enumerated-value completion, no argcomplete), plus a drift-guard test that introspects the real argparse subparsers | `contrib/completions/` (new), `token-finops-cli/tests/test_completions.py` (new), `docs/INSTALL.md`, `AGENTIC.md` | merged (PR #16) |
| Claude Opus 5 (local) | `feature/agentic/doctor-subcommand` | `token-finops doctor`: per-adapter found/empty/missing diagnosis with probed paths and one actionable hint each, Python/package version header, synth footer | `token-finops-cli/src/token_finops_cli/doctor.py` (new), `token-finops-cli/src/token_finops_cli/cli.py`, `token-finops-cli/tests/test_doctor.py` (new), `token-finops-cli/README.md` | merged (PR #12) |
| Claude Opus 5 (local) | `feature/agentic/claude-code-runway-skill` | T-04: agent-native `/runway` surface — a Claude Code skill (`runway/SKILL.md`) and the equivalent Codex custom prompt, both checking the runway *before* a sub-agent fan-out (`docs/INTEGRATIONS.md` §3), with a smoke test that parses every command string against the real argparse parser | `contrib/claude-code/` (new), `contrib/codex/` (new), `token-finops-cli/tests/test_contrib_skills.py` (new), `docs/INTEGRATIONS.md`, `docs/README.md`, `README.md`, `claude-tasks.md` | merged (PR #13) |
| Claude Opus 5 (local) | `feature/agentic/green-it-co2-reporting` | Green-IT reporting: cloud-side CO2/1M-tok estimate next to the existing local figure, US/DE grid carbon intensities re-sourced, `--co2` opt-in output, new 48 GB MacBook Pro M4 Max laptop profile | `token-finops-cli/src/token_finops_cli/savings/` (`__init__.py`, `energy.json`, `hardware_profiles.json`), `token-finops-cli/tests/test_cli_and_savings.py`, `docs/CO2_ESTIMATE.md` (new), `docs/sources.md`, `docs/savings.html`, `README.md`, `contrib/completions/*` | PR opened |
| Claude Opus 5 (local) | `feature/agentic/adr-0013-claude-desktop` | T-16: investigate `~/Library/Application Support/Claude/` read-only and write ADR-0013 (Claude Desktop / Cowork macOS coverage) | `docs/adr/0013-claude-desktop-cowork.md` (new), `docs/adr/README.md`, `docs/landscape.md`, `README.md` (one row), `claude-tasks.md`, `AGENTIC.md` | merged (PR #14) |
| Claude Opus 5 (local) | `feature/agentic/pypi-smoke-workflow` | Weekly `pypi-smoke.yml`: install the real published wheel across py3.10-3.13, smoke `adapters`/`synth`/`report`/`report --json` | `.github/workflows/pypi-smoke.yml` (new), `AGENTIC.md` | merged (PR #15) |

| Session | Branch | Task | Touches | Status |
|---|---|---|---|---|
| Claude Opus 5 (local) | `feature/agentic/pypi-smoke-workflow` | Weekly PyPI wheel smoke test: install the published `token-finops-cli` from the real index on 3.10–3.13 and run `--help` / `adapters` / `synth` / `report` / `report --json` / `cost-per-token` / `sessions` against a synthetic home. Closes the honesty gap where CI only ever tested the source checkout | `.github/workflows/pypi-smoke.yml` (new) | PR opened |
| Claude Sonnet 5 (cloud) | `feature/agentic/self-audit-compaction` | T-15: stitch every Claude Code transcript segment sharing a `sessionId` (compaction splits the main transcript into a new file) into one `self-audit` report, dedup across segments by `event_id`, print `segments: N` in the header | `token-finops-cli/src/token_finops_cli/adapters/claude_code.py`, `token-finops-cli/src/token_finops_cli/cli.py`, `token-finops-cli/tests/test_self_audit.py`, `docs/adr/0002-claude-code.md`, `claude-tasks.md` | [PR #10](https://github.com/qvest-ssels/burn-token-burn/pull/10) opened |

| Session | Branch | Task | Touches | Status |
|---|---|---|---|---|
| Claude Sonnet 5 (cloud) | `feature/agentic/awesome-lists-prep` | T-14 prep: researched QuesmaOrg/awesome-ai-tokenomics, pleasedodisturb/awesome-llm-token-optimization, plus awesome-claude-code/-codex-cli/-gemini-cli; drafted one-line entries + contribution-rule notes per list; no external PRs/issues/forks opened (release hasn't shipped) | `docs/AWESOME-LISTS.md` (new) | PR opened |
| Claude Sonnet 5 (cloud) | `feature/agentic/autoplay-and-wizard` | Scroll-triggered asciinema autoplay (`player.js`) + homepage install wizard (4-step, OS-aware, all steps visible) replacing the static install block; also folded README's support table + origin story onto the homepage | `docs/player.js`, `docs/index.html`, `docs/wizard.js` (new), `docs/style.css` | merged (PR #8) |
| Claude Sonnet 5 (cloud) | `feature/agentic/readme-docs-link` | Rebase a stray local README commit (GitHub Pages link) onto current `main` | `README.md` | superseded — same change landed via `feature/agentic/readme-and-home-rule` from a session with push access; this branch can be discarded |
| Claude Sonnet 5 (cloud) | `feature/agentic/statusline-enhancements` | `collect-statusline`: hash progress bar per window + opt-in sub-agent count/token summary (`TODOs.md` "Open" picks) | `token-finops-cli/src/token_finops_cli/cli.py`, `tests/test_statusline.py`, `docs/TMUX.md` | merged (PR #4) |
| Claude Sonnet 5 (local, push access) | `feature/agentic/readme-and-home-rule` | README GitHub Pages link + strengthen the home-directory rule with a no-self-cleanup clause | `README.md`, `AGENTS.md`, `AGENTIC.md` | merged (PR #6) |
| Claude Sonnet 5 (cloud) | `feature/agentic/copilot-synth-scale` | T-02: rebalance Copilot synthetic AIU economics (per-event scale + `DEFAULT_BUDGET_AIU`) to match real plan sizes instead of the old ~300x-too-hot fixture; verified against `compute_runway`'s pace-based CRITICAL rule, not just used-fraction thresholds | `token-finops-cli/src/token_finops_cli/adapters/copilot.py`, `synth/scenarios.py`, `tests/test_e2e_matrix.py`, `tests/test_usecases.py`, `tests/test_copilot.py`, `tests/test_cli_and_savings.py`, `docs/SYNTH.md`, `docs/USECASES.md`, `claude-tasks.md` | merged (PR #7) |

## Notes for whoever picks this up next

- This cloud session cannot authenticate to GitHub (no credentials in its sandbox), so
  branches it creates are handed to the human (Stefan) as a bundle to merge and push
  himself, or rebased directly on his Mac checkout via the device bridge. If you're an
  agent that *can* push, feel free to push these branches and open the PRs directly —
  just update the row above once you do.
- `qvest-ssels/burn-token-burn` is the leading remote (`origin`); `tronicum/burn-token-burn`
  is `upstream`. As of 2026-09-15 the `tronicum` identity does not have push access to
  `qvest-ssels/burn-token-burn` — see the "Remote / release housekeeping" section of
  `TODOs.md` for the options being considered.
