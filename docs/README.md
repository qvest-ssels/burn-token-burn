# Documentation index

Start with the repository root [`README.md`](../README.md) for the project
overview and [`AGENTS.md`](../AGENTS.md) for the rules coding agents (and
humans) follow in this repo. Everything below lives under `docs/`.

| Doc | What it covers |
|---|---|
| [`PLAN.md`](PLAN.md) | The structured plan, phase status, and the dogfooding record (self-audit snapshots from building this repo). |
| [`ADAPTERS.md`](ADAPTERS.md) | How to write an adapter: the `scan()`/`quota()`/`default_policy()`/`build_synthetic_*()` skeleton, plus verified field tables per assistant. |
| [`adr/`](adr/) | One Architecture Decision Record per coding assistant — data source, support tier, offline-quota availability, open questions. Start at [`adr/README.md`](adr/README.md) for the tiering rule. |
| [`SYNTH.md`](SYNTH.md) | The synthetic telemetry generator (`token-finops synth`): what it writes per tool, the seven burn-profile scenarios, and how the test suite uses it. |
| [`USECASES.md`](USECASES.md) | All 50 executable use cases, generated from `tests/test_usecases.py` — each row is a runnable pytest case. |
| [`BURN.md`](BURN.md) | `token-finops burn`: the maxing multiplier (plan vs. API-equivalent), plan-months, weekly/monthly tables, recorded history, and the burn-efficiency metric reference. |
| [`INSTALL.md`](INSTALL.md) | End-user install guide: how to install `token-finops` itself, plus the coding-agent CLI each adapter needs on disk and how to install it on macOS (Homebrew-first) and Linux. Tier 1 (Claude Code, Copilot CLI, Codex CLI, Gemini CLI, Hermes Agent, Cline/Roo/Kilo) is the current documentation + auto-test target; Tier 2 follows. |
| [`INTEGRATIONS.md`](INTEGRATIONS.md) | Design proposal for where the runway should be visible beyond the terminal: tmux/waybar/starship, editors, agent-native skills, desktop surfaces. The P0 item (`status` renderer + cache + `contrib/`) is implemented; see `TMUX.md`. Editors/GUI surfaces remain proposals. |
| [`landscape.md`](landscape.md) | The niche this project covers and the other local quota/runway trackers it happily points to instead of re-implementing. |
| [`sources.md`](sources.md) | Every price, quota, and endpoint used anywhere in the tool, with its source and a review date. |
| [`guide/`](guide/) | *The Qvest Digital Guide to Token Burning* — six chapters on what a token costs, where the money goes, right-sizing models, local vs. cloud, and governance. |
| [`../DEVELOPING.md`](../DEVELOPING.md) | Day-to-day dev workflow hub: environment, test subsets, synthetic telemetry + env var reference, debugging one adapter, the branch-per-task workflow, releasing. |
| [`../AUTOCODING.md`](../AUTOCODING.md) | Which CLI/model actually wrote this repo (cloud session vs. local Claude Code CLI fan-out), model-assignment rules, and the token accounting for each. |
| [`../CHANGELOG.md`](../CHANGELOG.md) | Release history. |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Setup, tests/lint, how to add an adapter, commit style, PR checklist. |
