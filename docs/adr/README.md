# Architecture Decision Records

This directory records, one ADR per AI coding assistant, why each tool gets
the level of support it gets in `token-finops`. Every ADR follows the same
question set: where the tool stores telemetry locally, what format and
fields are verified, what budget unit (if any) the provider actually
enforces and how it resets, whether remaining quota can be known offline,
online, or not at all, and whether the underlying data is official or
reverse-engineered. The resulting **support tier** — full adapter
(tokens + a real runway), usage-only (tokens/cost, no budget concept to
compute a runway against), reference-only (point to an existing tool
because local data is unreliable or absent), or not feasible (no local
data exists at all) — follows directly from those facts, not from how
popular or important a tool is. See `docs/ADAPTERS.md` for the
implementation conventions these decisions assume, and `docs/landscape.md`
for the tool links referenced as alternatives.

| ADR | Assistant | Proposed tier | Offline quota? | Data status |
|---|---|---|---|---|
| [0001](0001-github-copilot-cli.md) | GitHub Copilot CLI | Full adapter | Yes (local sum vs. plan allowance) | Official (RE cross-check optional) |
| [0002](0002-claude-code.md) | Claude Code | Full adapter | No (needs status-line collector or RE) | Official (statusline) / RE (oauth/usage) |
| [0003](0003-openai-codex-cli.md) | OpenAI Codex CLI | Full adapter | Yes (rate_limits in rollout) | Official (written to disk by Codex) |
| [0004](0004-gemini-cli.md) | Gemini CLI | Full adapter | Yes (requests/day, local count) | Official count; RE endpoint optional |
| [0005](0005-hermes-agent.md) | Hermes Agent | Usage-only + provider passthrough | Online only (OpenRouter key API) | Official (OpenRouter); no Hermes-level budget |
| [0006](0006-opencode-kilo-cli.md) | OpenCode / Kilo CLI | Usage-only | Not available | No budget concept found |
| [0007](0007-cline-roo-kilo-vscode.md) | Cline / Roo / Kilo (VS Code) | Usage-only | Not available | No budget concept found |
| [0008](0008-cursor.md) | Cursor | Reference-only | No (local field unreliable) | RE, cookie-authenticated only |
| [0009](0009-aider.md) | Aider | Usage-only (low priority) | Not available | Regex on human-facing log |
| [0010](0010-continue-dev.md) | Continue.dev | Usage-only (low confidence) | Not available | Unstable local field |
| [0011](0011-windsurf.md) | Windsurf | Not feasible / reference-only | No local data at all | Server-side only |
| [0012](0012-ollama-and-local-models.md) | Ollama & local models | No budget; feeds savings estimator | N/A (no budget concept) | Captured via client logs or a proxy |
