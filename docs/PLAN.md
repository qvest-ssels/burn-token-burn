# Plan: from token-finops-cli (Copilot) to a modular multi-assistant runway tracker

Status: **in progress** — last updated 2026-09-05. Decisions per assistant: `docs/adr/`.

## Goal

Keep everything `token-finops-cli` does for GitHub Copilot CLI (read the local telemetry, compute
a budget runway, `--watch`, `--compact`, session/break reports) and make it work, **modularly**, for
every coding assistant whose telemetry we can read — with one adapter per assistant, one ADR per
assistant, and a shared runway engine that never mixes units.

## Phase 0 — consolidate (this week)

1. `token-finops-cli/` is Stefan's original repository as a git subtree (full history). It becomes
   the **single package**; the interim `src/token_finops/` at the repo root is merged into it and removed.
2. Package layout after the merge (`token-finops-cli/src/token_finops_cli/`):
   `cli.py` (entry, keeps the original UX: plain `token-finops --since 7d` still works), `core/`
   (model, runway, pricing), `adapters/` (`copilot.py` is the original logic behind the common
   interface; others per ADR), `savings/`, `report.py`, `examples_helper.py` (kept for the
   original tests).
3. Repository root: `README.md`, `AGENTS.md`/`CLAUDE.md`, `docs/`, `LICENSE`, `.python-version`,
   `.github/workflows/ci.yml` (runs `uv run pytest` inside `token-finops-cli/`).
4. Environment: `uv venv && uv pip install -e "token-finops-cli[dev]"`. No system-site installs.

## Phase 1 — full adapters (runway-capable)

| Assistant | ADR | Runway source | State |
|---|---|---|---|
| GitHub Copilot CLI | 0001 | local AIU sum vs plan allowance, monthly reset 00:00 UTC | port done, tests green |
| Claude Code | 0002 | provider % via status-line collector (≥2 snapshots → burn) | done, needs real-world soak |
| OpenAI Codex CLI | 0003 | `rate_limits` in rollout JSONL (offline) | done against fixtures |
| Gemini CLI | 0004 | requests/day counted locally; optional online quota | done against fixtures |

## Phase 2 — usage-only adapters (tokens + API-equivalent, no intrinsic budget)

Hermes Agent (0005, done), OpenCode/Kilo CLI (0006), Cline/Roo/Kilo VS Code (0007), Aider (0009),
Continue.dev (0010). Each: `scan()` + fixture + test; `default_policy()` = USD, sliding 30 d,
allowance optional (`--allowance` gives them a runway against a self-set monthly budget).

## Phase 3 — reference-only / not feasible

Cursor (0008), Windsurf (0011): document, link to existing tools in `docs/landscape.md`, no adapter.
Ollama & local models (0012): no budget; throughput/energy feed the savings estimator via client logs.

## Phase 4 — cross-cutting

- `--online` flag: optional live quota fetchers (Copilot `copilot_internal/user`, Gemini
  `retrieveUserQuota`, OpenRouter key API, Anthropic `oauth/usage`) — each behind its ADR note,
  cached ≥ 3 min, never on by default.
- Savings: Fraunhofer ISE LCOE citation; Artificial-Analysis quality index for the
  "local model X ≈ cloud tier Y" mapping; `break-even` fed from all adapters.
- Guide: regenerate the self-audit numbers at release time and stamp the snapshot date.
- PRs to QuesmaOrg/awesome-ai-tokenomics and pleasedodisturb/awesome-llm-token-optimization.
- Release: `uv build`, tag `v0.2.0`, PyPI as `token-finops-cli` (continuity with the original name).

## Verification

`uv run pytest -q` (fixtures for every adapter), `uv run ruff check .`, real-data smoke on Stefan's
machine (`token-finops report` must reproduce the Copilot screenshots: 581 req / 62.5 M tok /
896.8 of 50 000 AIU / 125 d runway), `token-finops self-audit` on the building session.

## Dogfooding record

| Snapshot (UTC) | Calls | Tokens | API-eq | Fable | Sonnet | Haiku | Sub-agents |
|---|---|---|---|---|---|---|---|
| 2026-09-05 09:36 | 517 | 89.7 M (95 % cache reads) | $104 | 85 % | 15 % | ~0 % | 9 agents, 28 % |
