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
| Claude Sonnet 5 (cloud) | `feature/agentic/autoplay-and-wizard` | Scroll-triggered asciinema autoplay (`player.js`) + homepage install wizard (4-step, OS-aware, all steps visible) replacing the static install block; also folded README's support table + origin story onto the homepage | `docs/player.js`, `docs/index.html`, `docs/wizard.js` (new), `docs/style.css` | [PR #8](https://github.com/qvest-ssels/burn-token-burn/pull/8) opened |
| Claude Sonnet 5 (cloud) | `feature/agentic/readme-docs-link` | Rebase a stray local README commit (GitHub Pages link) onto current `main` | `README.md` | rebased, unpushed — needs a push target decision (`tronicum` has no write access to `qvest-ssels/burn-token-burn`, see `TODOs.md`) |
| Claude Sonnet 5 (cloud) | `feature/agentic/statusline-enhancements` | `collect-statusline`: hash progress bar per window + opt-in sub-agent count/token summary (`TODOs.md` "Open" picks) | `token-finops-cli/src/token_finops_cli/cli.py`, `tests/test_statusline.py`, `docs/TMUX.md` | ready for PR |

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
