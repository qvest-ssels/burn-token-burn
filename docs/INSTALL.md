# Installing token-finops and the coding agents it reads

This page is for end users: how to install `token-finops` itself, which coding-agent
CLI needs to already be on your machine for each adapter to find anything, and how to
install that CLI on macOS and Linux. `token-finops` never installs, updates, or talks to
any of these tools — it only reads the local files they already write.

**Install policy for the commands below:** macOS uses Homebrew wherever a formula or
cask exists; npm/pip is the documented fallback only when Homebrew has nothing. Linux
uses each tool's native path (npm, pipx/pip) by default. We do not document
`curl … | bash` / `irm … | iex` installers anywhere on this page, even when a project
offers one as its primary method — see the per-tool notes for where that means an
install is out of scope for now.

Review date: 2026-09-12. Package names, formula names, and version requirements move —
verify against the linked source before relying on a command in automation.

## Installing token-finops itself

`token-finops-cli` is not yet published to PyPI (tracked as
[T-05](../claude-tasks.md) in `claude-tasks.md`). Until then, install from a checkout:

```bash
git clone https://github.com/tronicum/burn-token-burn.git
cd burn-token-burn/token-finops-cli

# uv (recommended — no separate venv to manage)
uv tool install .

# pipx
pipx install .

# plain pip, in a virtualenv
python3 -m venv .venv && source .venv/bin/activate
pip install .
```

Once 0.3.0 is tagged and published, the same three tools will work directly against
the package name: `uv tool install token-finops-cli`, `pipx install token-finops-cli`,
`pip install token-finops-cli`.

Verify the install and see what it can already find on your machine:

```bash
token-finops --help
token-finops adapters
```

`adapters` lists every tool token-finops knows how to read and whether it found data for
it right now — that is also the smoke test after installing any of the CLIs below.

## Coding agents: what token-finops needs installed, and how to install it

Two rollout tiers. **Tier 1** is documented in full below and is the current target for
an automated install-smoke-test (a CI job that installs the real CLI on macOS and Linux
and confirms it runs — tracked as [T-18](../claude-tasks.md)). **Tier 2** already has a
working adapter and is documented in the README's tool table, but full install docs and
automated CLI installation come later.

| Tier | Tool |
|---|---|
| 1 (this page, auto-tested) | Claude Code, GitHub Copilot CLI, OpenAI Codex CLI, Gemini CLI, Hermes Agent*, Cline / Roo / Kilo (VS Code) |
| 2 (documented, not yet auto-tested) | OpenCode / Kilo CLI, Aider, Continue.dev |
| Reference-only (no local telemetry to read) | Cursor, Windsurf, Ollama — see `docs/adr/0008`, `0011`, `0012` |

\* Hermes Agent has no Homebrew formula and no pip/npm package as of this writing, so its
section below documents the official `curl | bash` installer as the sole exception to
this page's no-`curl | bash` rule. It's excluded from `cli-smoke.yml`'s CI matrix on
purpose — installing that way, unattended, on shared runners is a different risk
tradeoff than a person running it on their own machine.

---

### Claude Code

Reads: `~/.claude/projects/**/*.jsonl` (incl. `subagents/`) — see ADR-0002.

**macOS (Homebrew):**
```bash
brew install --cask claude-code
```
Cask installs lag the npm release by roughly a week and don't auto-update
(`brew upgrade --cask claude-code` to update).

**Linux (npm):**
```bash
npm install -g @anthropic-ai/claude-code   # requires Node.js 22+
```

Authenticate with `claude login` (or `/login` inside the CLI) on first run.

Source: [Anthropic's install guide, as summarised by morphllm.com](https://www.morphllm.com/install-claude-code) — verify against `https://docs.claude.com` before scripting.

### GitHub Copilot CLI

Reads: `~/.copilot/session-store.db` (`assistant_usage_events`) — see ADR-0001.

No Homebrew formula exists yet for `@github/copilot`; npm is the documented path on
both macOS and Linux.

```bash
npm install -g @github/copilot   # requires Node.js 22+
```

If your `~/.npmrc` sets `ignore-scripts=true`, this package needs its postinstall step:
```bash
npm_config_ignore_scripts=false npm install -g @github/copilot
```

Authenticate with the `/login` slash command on first launch, or export a fine-grained
PAT with the "Copilot Requests" permission as `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or
`GITHUB_TOKEN` (checked in that order).

Source: [GitHub Docs — Install Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli).

### OpenAI Codex CLI

Reads: `~/.codex/sessions/**/rollout-*.jsonl` (incl. `rate_limits`) — see ADR-0003.

**macOS (Homebrew):**
```bash
brew install --cask codex
```

**Linux (npm):**
```bash
npm install -g @openai/codex
```
Use the scoped package name `@openai/codex` — an unrelated, unscoped `codex` package
exists on npm and is not this tool.

Authenticate with `codex login` (ChatGPT Plus/Pro sign-in) or an API key, per
`codex --help`.

Sources: [openai/codex releases](https://github.com/openai/codex/releases), [Homebrew cask: codex](https://formulae.brew.sh/cask/codex). Note several open issues on `brew upgrade codex` lagging or picking the wrong architecture on Apple Silicon — check `codex --version` after install.

### Gemini CLI

Reads: `~/.gemini/tmp/*/chats/*.jsonl` — see ADR-0004.

**macOS (Homebrew) — see caveat below:**
```bash
brew install gemini-cli
```
Homebrew currently lists this formula **deprecated**, with a disable date of
2026-12-18 and `antigravity-cli` named as the replacement. Confirm the formula still
resolves before relying on it in a script, and reprioritise this tool's Tier-1 slot
if it's gone by the time you read this.

**Linux (npm):**
```bash
npm install -g @google/gemini-cli   # requires Node.js 20+
```

Authenticate with a Google account on first run (`gemini`) or an API key via
`GEMINI_API_KEY`.

Sources: [npm: @google/gemini-cli](https://www.npmjs.com/package/@google/gemini-cli), [Homebrew formula: gemini-cli](https://formulae.brew.sh/formula/gemini-cli), [Gemini CLI install docs](https://geminicli.com/docs/get-started/installation/).

### Cline / Roo / Kilo (VS Code extensions)

Reads: `<VS Code globalStorage>/<extension-id>/tasks/*/ui_messages.json` — see ADR-0007.

These are VS Code extensions, not standalone CLIs — Homebrew installs the editor, and
the editor's own `code` CLI installs the extension.

**macOS (Homebrew, for the editor):**
```bash
brew install --cask visual-studio-code
```

**Then, on macOS or Linux, once `code` is on your PATH** (VS Code: Command Palette →
"Shell Command: Install 'code' command in PATH"):

```bash
code --install-extension saoudrizwan.claude-dev       # Cline
code --install-extension RooVeterinaryInc.roo-cline   # Roo Code
code --install-extension kilocode.Kilo-Code           # Kilo Code
```

Extension IDs occasionally change on republish — confirm against the extension's
marketplace page before scripting this.

Sources: [Roo Code — Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=RooVeterinaryInc.roo-cline), [Kilo Code — Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=kilocode.Kilo-Code).

### Hermes Agent (NousResearch) — the one documented exception to "no curl\|bash"

Reads: `~/.hermes/state.db` — see ADR-0005.

Checked again on 2026-09-12: no Homebrew formula/tap, no apt/deb, no AUR, no pip or npm
package. [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
ships only its own installer script, for every platform including Termux — there is
currently no other way in. Given that, this is the one place on this page we document
the official installer rather than withholding a command:

**macOS and Linux:**
```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

Read the script before piping it to a shell if that matters to you —
[`scripts/install.sh`](https://github.com/NousResearch/hermes-agent/blob/main/scripts/install.sh)
is the one this command fetches. It brings its own Python 3.11, Node.js, ripgrep,
ffmpeg and Git. Revisit this exception once the project ships a package-manager
install; every other tool on this page stays brew/npm/pip-only.

---

## Tier 2 (documented in the README, install docs pending)

OpenCode / Kilo CLI, Aider, and Continue.dev already have working adapters (ADR-0006,
0009, 0010) but don't yet have the same install-doc + auto-test treatment. OpenCode has
a Homebrew formula (`brew install opencode`); Aider and Continue.dev are pip/marketplace
installs respectively with no confirmed Homebrew path as of this review — both are
candidates for the next round once Tier 1's CI job is in place.

## What "auto-tested" means here (T-18)

This page's Tier-1 commands are the input to a planned CI job, not a claim that CI
already runs them: install the real CLI on `macos-latest` and `ubuntu-latest`, assert it
resolves on `PATH` and answers `--version`/`--help`. That validates the *install*
instructions on this page. It intentionally does not attempt to authenticate any of
these tools or generate real usage telemetry in CI — that needs a live account per
tool, which a shared CI runner cannot hold. Real usage telemetry is instead exercised
against the synthetic fixtures (`token-finops synth`, `tests/test_e2e_matrix.py`) as
described in `docs/SYNTH.md`.
