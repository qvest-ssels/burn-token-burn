# Token FinOps Status (VS Code extension)

Status-bar runway indicator for [`token-finops`](../../README.md), for the audience
already running Cline / Roo / Kilo / Continue.dev as VS Code extensions
(see [`docs/adr/0007-cline-roo-kilo-vscode.md`](../../docs/adr/0007-cline-roo-kilo-vscode.md)).

- **Status bar**: binding-constraint tool's short name, used %, runway, and a
  status glyph (`CC 41% 6d`), colouring the segment on WARN/CRITICAL/EXHAUSTED.
- **Click → detail webview**: the full per-tool table (tool, window, used %,
  runway, status), same shape as `token-finops status --format json`.
- **Command palette**: `Token FinOps: Show Runway Detail`, `Token FinOps: Refresh Now (--fresh)`.

## Cache vs. shell-out

The periodic status-bar tick reads `~/.token-finops/last.json` directly rather
than shelling out to the CLI on every poll. This is the same tradeoff
`contrib/tmux` and `contrib/nvim` make:

- **Reading the cache** (chosen for the timer): instant, zero process-spawn
  cost, safe to poll every 10-60s. Tradeoff: it's only as fresh as whatever
  already refreshes `last.json` — a cron job, `contrib/refresh`, another
  widget calling `--fresh`, or this extension's own manual refresh below. If
  nothing refreshes the cache, the status bar shows a stale (or missing) snapshot.
- **Shelling out** (chosen for the manual command only): `Token FinOps: Refresh
  Now (--fresh)` runs `token-finops status --fresh --format json` on demand,
  which rescans telemetry and rewrites the cache as a side effect. It's rate
  limited to one call per 10s so repeated clicks (or a flaky binding) can't
  spawn a process storm. It is **not** on the poll timer — only ever runs when
  you invoke the command.

If you don't already have a refresh timer running, either invoke `Refresh Now`
periodically yourself, or set one up per [`docs/TMUX.md`](../../docs/TMUX.md) /
`contrib/refresh`'s pattern (a cron/launchd job calling `token-finops status --fresh`
on an interval) and let every widget — this one included — read the same cache.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `tokenFinops.cliPath` | `token-finops` | Binary/wrapper used **only** by "Refresh Now" (e.g. `uv run token-finops` if the CLI isn't on `PATH`). Never used by the polling tick. |
| `tokenFinops.pollIntervalSeconds` | `45` | How often the status bar re-reads the cache file (min 10s). This never spawns a process. |
| `tokenFinops.showAll` | `false` | Include `UNLIMITED` (usage-only, no allowance) tools, matching `token-finops status --all`. |

## Install (local / manual — not published to the Marketplace)

This extension is not published to the VS Code Marketplace as part of this
task; publishing an extension requires a publisher account and is a
human/account-owner action (same category as the PyPI/Homebrew publishing
steps flagged elsewhere in this repo). Two ways to run it locally:

### Option A — Extension Development Host (fastest, for trying it out)

1. Open `contrib/vscode/` as a folder in VS Code (`code contrib/vscode`).
2. Press `F5` (or Run → Start Debugging). VS Code launches a second
   "Extension Development Host" window with the extension active.
3. Check the status bar (bottom right) for the `token-finops` segment.

No build step is required — the extension is plain JavaScript
(`extension.js`), not TypeScript, specifically so it runs directly without
`npm install`/a compiler. See "Why plain JS, not TypeScript" below.

### Option B — Package and install into your normal VS Code

Packaging into a `.vsix` needs [`@vscode/vsce`](https://github.com/microsoft/vscode-vsce), which is
**not installed in this repo/environment** — it wasn't installed as part of
this task per this repo's ask-before-installing-packages rule. To do it
yourself:

```bash
cd contrib/vscode
npm install -g @vscode/vsce      # or: npx --yes @vscode/vsce package
vsce package                      # writes token-finops-status-0.1.0.vsix
code --install-extension token-finops-status-0.1.0.vsix
```

Reload VS Code (`Developer: Reload Window`) after installing.

## Why plain JavaScript, not TypeScript

A small contrib extension like this doesn't need TypeScript's type-checking
to stay correct — the surface is one file, a handful of `vscode` API calls,
and no complex data model. Using plain JS means:

- No `tsconfig.json`, no `@types/vscode`/`@types/node` devDependencies, no
  build step (`tsc`) between editing and running.
- `extension.js` runs directly under the Extension Development Host (Option A
  above) with nothing to install first.

The tradeoff: no compile-time type checking against the `vscode` API surface.
Given the extension's small size and that its only external dependency is the
`vscode` module itself (whose shape is stable and well-documented at
<https://code.visualstudio.com/api/references/vscode-api>), this was judged
not worth the added tooling weight for a `contrib/` extension. If this ever
grows into something published to the Marketplace, converting to TypeScript
first would be reasonable.

## Data source

Reads the same cache contract `token-finops status` writes and documents at
the top of
[`token_finops_cli/status.py`](../../token-finops-cli/src/token_finops_cli/status.py):

```json
{
  "schema_version": 1,
  "generated_at": "<ISO-8601 UTC>",
  "tools": [ /* same objects `report --json` emits */ ],
  "binding": { "tool": "...", "display_name": "...", "runway_days": 6, "status": "WARN", "...": "..." } | null
}
```

If `~/.token-finops/last.json` doesn't exist yet, run `token-finops status`
once from a terminal (see the main [README](../../README.md)) to create it.

## Verification status

**Not built or run in an actual VS Code instance during development** — this
environment has `node`/`npm` available, but installing the extension-authoring
tooling this would need to fully verify (`@vscode/vsce` for packaging, or
`@types/vscode` if this were TypeScript) wasn't done without asking first, per
this repo's ask-before-installing-packages rule. The code is written directly
against the documented, stable `vscode` extension API
(`window.createStatusBarItem`, `window.createWebviewPanel`,
`commands.registerCommand`, `workspace.getConfiguration`,
`window.createOutputChannel`) — see
<https://code.visualstudio.com/api/references/vscode-api> — but treat it as
unverified until someone runs Option A above and confirms the status bar and
webview render correctly.
