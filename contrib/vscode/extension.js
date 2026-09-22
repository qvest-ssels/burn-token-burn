// Token FinOps status-bar extension.
//
// Reads the same cache contract as `token-finops status` (see
// token-finops-cli/src/token_finops_cli/status.py, docstring at the top of that
// file): ~/.token-finops/last.json, written by whatever already-running refresh
// loop the user has (cron, `contrib/refresh`, tmux/waybar/etc. calling `--fresh`,
// or this extension's own "Refresh Now" command).
//
// Design choice (see contrib/vscode/README.md "Cache vs shell-out" for the
// tradeoff writeup): the periodic status-bar tick reads the cache file directly
// -- instant, no process spawn, same pattern as contrib/tmux and contrib/nvim --
// rather than shelling out to the CLI on every tick. A "Refresh Now" command is
// provided for the times you want a live `--fresh` rescan on demand; it shells
// out and is not on any timer, so it can't runaway-spawn processes.
//
// VS Code API surfaces used here (extension API, stable since well before 1.80):
//   vscode.window.createStatusBarItem      https://code.visualstudio.com/api/references/vscode-api#StatusBarItem
//   vscode.window.createWebviewPanel       https://code.visualstudio.com/api/references/vscode-api#WebviewPanel
//   vscode.commands.registerCommand        https://code.visualstudio.com/api/references/vscode-api#commands.registerCommand
//   vscode.window.createOutputChannel      https://code.visualstudio.com/api/references/vscode-api#OutputChannel

"use strict";

const vscode = require("vscode");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { exec } = require("child_process");

const CACHE_FILE = path.join(os.homedir(), ".token-finops", "last.json");

// Mirrors status.py's SHORT / GLYPH tables so the status bar segment reads the
// same as every other widget (tmux, waybar, starship, ...). Keep these two
// tables in sync with token-finops-cli/src/token_finops_cli/status.py if that
// file's tables ever change.
const SHORT = {
  copilot: "CP",
  claude_code: "CC",
  codex: "CX",
  gemini_cli: "GM",
  hermes: "HM",
  opencode: "OC",
  cline: "CL",
  aider: "AI",
  continue_dev: "CT",
  continue: "CT",
};
const GLYPH = {
  OK: "",
  WARN: "!",
  CRITICAL: "!!",
  EXHAUSTED: "X",
  UNLIMITED: "",
  UNKNOWN: "?",
};
// VS Code status-bar background colors it ships built-in theme colors for;
// used to make WARN/CRITICAL/EXHAUSTED visually pop the same way the other
// status.py renderers colour their segment.
const BG_COLOR = {
  WARN: "statusBarItem.warningBackground",
  CRITICAL: "statusBarItem.errorBackground",
  EXHAUSTED: "statusBarItem.errorBackground",
};

let statusBarItem;
let pollTimer;
let detailPanel;
let outputChannel;
let lastRefreshAt = 0;
const MIN_REFRESH_GAP_MS = 10_000; // rate-limit the manual/shell-out refresh

function shortName(tool) {
  return SHORT[tool] || String(tool || "").slice(0, 2).toUpperCase();
}

function fmtRunway(days) {
  if (days === null || days === undefined) return "n/a";
  if (typeof days === "number" && !isFinite(days)) return "inf";
  if (days < 1) return `${Math.round(days * 24)}h`;
  return `${Math.round(days)}d`;
}

function fmtPct(x) {
  return x === null || x === undefined ? "?" : `${Math.round(x * 100)}%`;
}

function runwayOf(t) {
  // null runway on an OK tool means "no burn yet" -> unbounded, not unknown
  // (same special case as status.py's _runway_of).
  if ((t.runway_days === null || t.runway_days === undefined) && t.status === "OK") {
    return "inf";
  }
  return fmtRunway(t.runway_days);
}

function readCache() {
  try {
    const raw = fs.readFileSync(CACHE_FILE, "utf8");
    const snap = JSON.parse(raw);
    if (snap.schema_version !== 1) return null; // schema drift guard, see status.py
    return snap;
  } catch (err) {
    return null;
  }
}

function visibleTools(snapshot, showAll) {
  const tools = snapshot.tools || [];
  if (showAll) return tools;
  return tools.filter((t) => t.status !== "UNLIMITED");
}

function updateStatusBar() {
  const cfg = vscode.workspace.getConfiguration("tokenFinops");
  const showAll = cfg.get("showAll", false);
  const snapshot = readCache();

  if (!snapshot) {
    statusBarItem.text = "$(circle-slash) token-finops: no data";
    statusBarItem.tooltip = `No readable cache at ${CACHE_FILE}.\nRun "token-finops status" once, or a refresh timer (contrib/refresh), to populate it.`;
    statusBarItem.backgroundColor = undefined;
    statusBarItem.show();
    return;
  }

  const tools = visibleTools(snapshot, showAll);
  const binding = snapshot.binding;
  let text;
  let status;
  if (binding) {
    status = binding.status;
    text = `$(pulse) ${shortName(binding.tool)} ${fmtPct(binding.used_fraction)} ${runwayOf(binding)}${GLYPH[status] || ""}`;
  } else if (tools.length) {
    const t = tools[0];
    status = t.status;
    text = `$(pulse) ${shortName(t.tool)} ${fmtPct(t.used_fraction)} ${runwayOf(t)}${GLYPH[status] || ""}`;
  } else {
    status = "UNKNOWN";
    text = "$(pulse) token-finops: no tools";
  }

  statusBarItem.text = text;
  statusBarItem.backgroundColor = BG_COLOR[status]
    ? new vscode.ThemeColor(BG_COLOR[status])
    : undefined;

  const genAt = snapshot.generated_at ? new Date(snapshot.generated_at) : null;
  const ageLine = genAt ? `\nCache generated: ${genAt.toLocaleString()}` : "";
  statusBarItem.tooltip = `token-finops -- click for full detail${ageLine}\n(source: ${CACHE_FILE})`;
  statusBarItem.command = "tokenFinops.showDetail";
  statusBarItem.show();

  if (detailPanel) {
    detailPanel.webview.html = renderDetailHtml(snapshot, tools);
  }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// Renders the same per-tool table shape status.py's render_json/render_plain
// expose, as plain HTML -- no framework, per the task's "no need for a fancy
// UI framework" call.
function renderDetailHtml(snapshot, tools) {
  const genAt = snapshot.generated_at ? new Date(snapshot.generated_at).toLocaleString() : "unknown";
  const binding = snapshot.binding;
  const rows = tools
    .map((t) => {
      const isBinding = binding && binding.tool === t.tool;
      return `<tr class="${isBinding ? "binding" : ""} status-${escapeHtml(t.status || "unknown").toLowerCase()}">
        <td>${escapeHtml(t.display_name || t.tool)}${isBinding ? " <span class=\"tag\">binding</span>" : ""}</td>
        <td>${escapeHtml(t.window || "")}</td>
        <td>${escapeHtml(fmtPct(t.used_fraction))}</td>
        <td>${escapeHtml(runwayOf(t))}</td>
        <td>${escapeHtml(t.status || "")}</td>
      </tr>`;
    })
    .join("\n");

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { font-family: var(--vscode-font-family, sans-serif); color: var(--vscode-foreground); padding: 0 1rem; }
  h2 { font-weight: 600; }
  .meta { color: var(--vscode-descriptionForeground); margin-bottom: 1rem; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 0.4rem 0.8rem; border-bottom: 1px solid var(--vscode-panel-border, #444); }
  tr.binding td:first-child { font-weight: 600; }
  .tag { font-size: 0.75em; padding: 0.1em 0.5em; border-radius: 3px; background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); }
  tr.status-warn td:nth-child(5) { color: var(--vscode-editorWarning-foreground, #e5c07b); }
  tr.status-critical td:nth-child(5), tr.status-exhausted td:nth-child(5) { color: var(--vscode-editorError-foreground, #e06c75); }
  .empty { color: var(--vscode-descriptionForeground); font-style: italic; }
</style>
</head>
<body>
  <h2>token-finops runway</h2>
  <div class="meta">cache generated: ${escapeHtml(genAt)} &middot; source: ${escapeHtml(CACHE_FILE)}</div>
  ${
    rows
      ? `<table>
    <thead><tr><th>Tool</th><th>Window</th><th>Used</th><th>Runway</th><th>Status</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`
      : '<p class="empty">No tools to show (enable "tokenFinops.showAll" to include usage-only tools with no allowance).</p>'
  }
</body>
</html>`;
}

function showDetailPanel(context) {
  if (detailPanel) {
    detailPanel.reveal(vscode.ViewColumn.Beside);
    return;
  }
  detailPanel = vscode.window.createWebviewPanel(
    "tokenFinopsDetail",
    "Token FinOps",
    vscode.ViewColumn.Beside,
    { enableScripts: false }
  );
  const cfg = vscode.workspace.getConfiguration("tokenFinops");
  const snapshot = readCache();
  detailPanel.webview.html = snapshot
    ? renderDetailHtml(snapshot, visibleTools(snapshot, cfg.get("showAll", false)))
    : `<p>No readable cache at ${escapeHtml(CACHE_FILE)}. Run <code>token-finops status</code> once to populate it.</p>`;
  detailPanel.onDidDispose(() => {
    detailPanel = undefined;
  }, null, context.subscriptions);
}

function refreshNow() {
  const now = Date.now();
  if (now - lastRefreshAt < MIN_REFRESH_GAP_MS) {
    vscode.window.setStatusBarMessage("token-finops: refresh rate-limited, try again shortly", 3000);
    return;
  }
  lastRefreshAt = now;
  const cfg = vscode.workspace.getConfiguration("tokenFinops");
  const bin = cfg.get("cliPath", "token-finops");
  outputChannel.appendLine(`$ ${bin} status --fresh --format json`);
  exec(`${bin} status --fresh --format json`, { timeout: 30_000 }, (err, stdout, stderr) => {
    if (err) {
      outputChannel.appendLine(`error: ${err.message}`);
      if (stderr) outputChannel.appendLine(stderr);
      vscode.window.showErrorMessage(
        `token-finops refresh failed (see "Token FinOps" output channel): ${err.message}`
      );
      return;
    }
    outputChannel.appendLine("refresh ok, cache updated");
    // `status --fresh` already rewrites ~/.token-finops/last.json as a side
    // effect (status.py cmd_status), so a plain re-read picks it up.
    updateStatusBar();
  });
}

function activate(context) {
  outputChannel = vscode.window.createOutputChannel("Token FinOps");
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  context.subscriptions.push(statusBarItem, outputChannel);

  context.subscriptions.push(
    vscode.commands.registerCommand("tokenFinops.showDetail", () => showDetailPanel(context))
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("tokenFinops.refresh", refreshNow)
  );

  const cfg = vscode.workspace.getConfiguration("tokenFinops");
  const intervalMs = Math.max(10, cfg.get("pollIntervalSeconds", 45)) * 1000;

  updateStatusBar();
  pollTimer = setInterval(updateStatusBar, intervalMs);
  context.subscriptions.push({ dispose: () => clearInterval(pollTimer) });

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("tokenFinops")) {
        clearInterval(pollTimer);
        const newCfg = vscode.workspace.getConfiguration("tokenFinops");
        const newIntervalMs = Math.max(10, newCfg.get("pollIntervalSeconds", 45)) * 1000;
        pollTimer = setInterval(updateStatusBar, newIntervalMs);
        updateStatusBar();
      }
    })
  );
}

function deactivate() {
  if (pollTimer) clearInterval(pollTimer);
}

module.exports = { activate, deactivate };
