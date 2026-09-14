# Landscape: local quota & runway trackers for coding agents

This page covers **one niche only**: per-developer, local, read-only tools that read the telemetry an AI coding agent leaves on your own disk and tell you what you used and how much is left. For everything else — proxies, OTEL, eBPF, prompt compression, KV-cache papers — two excellent awesome-lists already exist and we send our PRs there instead of maintaining a third:
[QuesmaOrg/awesome-ai-tokenomics](https://github.com/QuesmaOrg/awesome-ai-tokenomics) ·
[pleasedodisturb/awesome-llm-token-optimization](https://github.com/pleasedodisturb/awesome-llm-token-optimization).

## GitHub Copilot CLI

| Tool | Link | Notes |
|---|---|---|
| **token-finops-cli** | [oh-my-agent-code/token-finops-cli](https://github.com/oh-my-agent-code/token-finops-cli) | The original this repository ports: reads `~/.copilot/session-store.db`, monthly AI-credit budget runway, `--watch`, `--compact`. Python stdlib, AGPL-3.0. |
| **ccusage** (Copilot source) | [ryoppippi/ccusage](https://github.com/ryoppippi/ccusage) | Multi-agent cost reports; Copilot is one of 14+ sources. |

## Claude Code

| Tool | Link | Notes |
|---|---|---|
| **ccusage** | [ryoppippi/ccusage](https://github.com/ryoppippi/ccusage) · [ccusage.com](https://ccusage.com/) | Most mature. Cost reports by day/month/session/5-hour block, live monitor, MCP server, LiteLLM pricing. |
| **Claude Code Usage Monitor** | [Maciek-roboblog/Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) | Burn rate and forecast of when the session limit is hit; P90-based limit learning. Conceptually closest to a "runway". |
| **ccburn** | [JuanjoFuchs/ccburn](https://github.com/JuanjoFuchs/ccburn) | Terminal UI with consumption charts and burn-rate relative to the billing window. |
| **claude-usage** | [phuryn/claude-usage](https://github.com/phuryn/claude-usage) | Local dashboard; progress bar for Pro/Max plans. |
| **claude-spend** | npm | One-command, zero-config cost check per conversation/model. |
| **CodeBurn** | [getagentseal/codeburn](https://github.com/getagentseal/codeburn) | Spend by turn type, correlated with git history; flags retry loops and abandoned sessions. |
| **Claude Code Usage Monitor (Windows taskbar)** | [CodeZeno/Claude-Code-Usage-Monitor](https://github.com/CodeZeno/Claude-Code-Usage-Monitor) | Windows taskbar variant. |
| **usage-monitor-for-claude** | [jens-duttke/usage-monitor-for-claude](https://github.com/jens-duttke/usage-monitor-for-claude) | Windows tray app, single portable EXE, rate limits in real time. |
| **ai-token-monitor** | [soulduse/ai-token-monitor](https://github.com/soulduse/ai-token-monitor) | macOS menu bar app for Claude Code tokens/costs. |
| **Claude-Usage-Tracker** | [hamed-elfayome/Claude-Usage-Tracker](https://github.com/hamed-elfayome/Claude-Usage-Tracker) | Native macOS menu bar app (Swift/SwiftUI) for real-time usage limits. |
| **claude-context-optimizer** | community | Context-budget heatmaps; flags instructions that rarely influence output. |

## Claude Desktop & Cowork (macOS)

The desktop chat app keeps **no** local usage telemetry — conversations are server-side, and the
only token-shaped data on disk is inside the claude.ai webview's IndexedDB cache, which is
undocumented, incomplete and interleaved with raw conversation text (see
[ADR-0013](adr/0013-claude-desktop-cowork.md) for what is and is not in
`~/Library/Application Support/Claude/`). Two things *are* usable: Desktop caches the
account-wide 5 h / 7 d quota utilisation with ~30 days of history in `plan-usage-history.json`,
and **on-computer** Cowork mirrors its transcripts — tokens, USD and window utilisation — onto
the Mac in `local-agent-mode-sessions/**/audit.jsonl`. **Cloud** Cowork sessions leave nothing on
the Mac; run `token-finops self-audit` inside the session and export the JSON into your repo.

| Tool | Link | Notes |
|---|---|---|
| **claude-usage-tracker** | [658jjh/claude-usage-tracker](https://github.com/658jjh/claude-usage-tracker) | The only tracker we found advertising Claude Desktop coverage. Paths are heuristic — treat desktop-chat figures as indicative, not billed. |
| **Claude-Usage-Tracker** (menu bar) | [hamed-elfayome/Claude-Usage-Tracker](https://github.com/hamed-elfayome/Claude-Usage-Tracker) | Native macOS menu bar app for the account-wide limits — the same number Desktop caches locally. |
| **usage-monitor-for-claude** | [jens-duttke/usage-monitor-for-claude](https://github.com/jens-duttke/usage-monitor-for-claude) | Rate-limit windows in real time (Windows tray). |

## OpenAI Codex CLI

| Tool | Link | Notes |
|---|---|---|
| **ccusage/codex** | [ccusage.com/guide/codex](https://ccusage.com/guide/codex/) | Parses rollout JSONL `token_count` events. |
| **codex-check** | [Leask/codex-check](https://github.com/Leask/codex-check) | Reads auth + limits, `--json` output. |
| **CodexBar** | [steipete/CodexBar](https://github.com/steipete/CodexBar) | macOS menu bar; Codex and Gemini quota. |

## Gemini CLI

| Tool | Link | Notes |
|---|---|---|
| **gemini-cost-tracker** | [ronkovic/gemini-cost-tracker](https://github.com/ronkovic/gemini-cost-tracker) | Gemini API / Vertex AI cost tracking. |
| **geminiusage** | [rmedranollamas/geminiusage](https://github.com/rmedranollamas/geminiusage) | Gemini CLI token usage tracker. |
| **agy-quota** | [tingyi365/agy-quota](https://github.com/tingyi365/agy-quota) | Gemini / Antigravity (Code Assist) quota via the internal quota endpoint. |

## Hermes Agent

| Tool | Link | Notes |
|---|---|---|
| **ccusage/hermes** | [ccusage.com/guide/hermes](https://ccusage.com/guide/hermes/) | Experimental Hermes source. |
| **hermes-token-cost** | [muntasirrmahdi/hermes-token-cost](https://github.com/muntasirrmahdi/hermes-token-cost) | Plugin reading `state.db` read-only. |
| **hermes-dashboard** | [Bichev/hermes-dashboard](https://github.com/Bichev/hermes-dashboard) | Dashboard over `state.db` plus a proxy DB (Anthropic pricing only). |

## Cross-tool (several agents in one view)

| Tool | Link | Covers |
|---|---|---|
| **tokscale** | [junhoyeo/tokscale](https://github.com/junhoyeo/tokscale) | Rust; Claude Code, Codex, Gemini, Hermes, OpenCode, Kilo, Cline, Roo, Cursor (via CSV). Good field-alias lists. |
| **OpenTokenMonitor** | [Hitheshkaranth/OpenTokenMonitor](https://github.com/Hitheshkaranth/OpenTokenMonitor) | Claude, Codex, Gemini/Antigravity — local, privacy-first, Tauri app. |
| **cc-statistics** | [androidZzT/cc-statistics](https://github.com/androidZzT/cc-statistics) | Claude Code, Gemini CLI, Codex, Cursor in one dashboard; pure-stdlib Python. |
| **claude-usage-tracker** | [658jjh/claude-usage-tracker](https://github.com/658jjh/claude-usage-tracker) | Very broad (OpenClaw, Claude Code/Desktop, Cursor, Windsurf, Cline, Roo, Aider, Continue) — some paths are heuristic. |
| **Token Tracker** | [tokentracker.cc](https://www.tokentracker.cc/) | Web tool spanning several coding CLIs. |

## IDE agents and others

| Tool | Link | Notes |
|---|---|---|
| **cursor-stats** | [Dwtexe/cursor-stats](https://github.com/Dwtexe/cursor-stats) | Cursor usage via dashboard API (GPL-3.0). Local `tokenCount` in Cursor's DB is unreliable per Cursor staff. |
| **openusage** | [robinebers/openusage](https://github.com/robinebers/openusage) | OpenCode plan caps from local files. |
| **agent-opencode** | [tokentopapp/agent-opencode](https://github.com/tokentopapp/agent-opencode) | OpenCode `opencode.db` reader. |

## What token-finops adds

Nobody else normalises *limits* across tools: existing trackers report spend in USD (via LiteLLM prices) and, where the provider offers one, a percentage. `token-finops` computes a **runway and pace ratio per tool in the unit that provider actually enforces** — Copilot credits, Claude/Codex window percentages, Gemini requests per day, OpenRouter dollars — and rolls them up as a **binding constraint** (whichever runs out first) instead of summing incompatible units. It also replays your real usage against a local box to answer "would a Mac Studio have paid off by now?" (`break-even`), pricing solar at the feed-in tariff you forgo rather than at zero.

Last reviewed: 2026-09-14
