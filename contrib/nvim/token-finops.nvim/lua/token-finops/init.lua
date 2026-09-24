--- token-finops.nvim: read-only Neovim frontend for `~/.token-finops/last.json`.
---
--- This plugin NEVER invokes the `token-finops` CLI itself and NEVER rescans your
--- assistants' telemetry. It only reads the cache file that `token-finops status`
--- (or the refresh timer in contrib/refresh/) already wrote, exactly like the tmux
--- integration in contrib/tmux/ does with `token-finops status --max-age 0`. Keep
--- the cache warm with the refresh timer; this plugin is a dumb, cheap reader.
---
--- Cache contract (docs/INTEGRATIONS.md §5.1, token_finops_cli/status.py):
---   {
---     "schema_version": 1,
---     "generated_at": "<ISO-8601 UTC>",
---     "tools": [ {tool, display_name, window, unit, used, allowance, used_fraction,
---                 runway_days, status, ...}, ... ],
---     "binding": {tool, display_name, window, runway_days, used_fraction, status} | null
---   }

local M = {}

-- SCHEMA_VERSION in token_finops_cli/status.py. Bump this alongside the CLI if the
-- cache contract ever changes shape.
local SUPPORTED_SCHEMA_VERSION = 1

-- Mirrors status.py's SHORT/GLYPH maps for a consistent look across surfaces
-- (tmux, waybar, xbar, …). Not required to match exactly — see README for
-- anywhere this plugin intentionally diverges.
local SHORT = {
  copilot = "CP", claude_code = "CC", codex = "CX", gemini_cli = "GM", hermes = "HM",
  opencode = "OC", cline = "CL", aider = "AI", continue_dev = "CT", continue = "CT",
}
local GLYPH = {
  OK = "", WARN = "!", CRITICAL = "!!", EXHAUSTED = "X", UNLIMITED = "", UNKNOWN = "?",
}

M.config = {
  -- The CLI's status.py has no env-var override for the cache path today (only a
  -- --cache-file CLI flag on `token-finops status`), so the honest default is the
  -- hardcoded path used everywhere else in contrib/. We still let the user override
  -- it here (setup({cache_path = ...}) or $TOKEN_FINOPS_CACHE) for local experiments,
  -- but that env var is a convention of this plugin, not something the CLI reads.
  cache_path = vim.fn.expand("~/.token-finops/last.json"),
  stale_after_seconds = 600, -- health check warns past this; status.py's refresh timers run every 60-300s
}

local function short_name(tool)
  return SHORT[tool] or string.upper(string.sub(tool or "??", 1, 2))
end

local function glyph(status)
  return GLYPH[status] or ""
end

--- Resolve the effective cache path: setup() opt > $TOKEN_FINOPS_CACHE > default.
function M.cache_path()
  local env = vim.fn.getenv("TOKEN_FINOPS_CACHE")
  if env ~= vim.NIL and env ~= nil and env ~= "" then
    return vim.fn.expand(env)
  end
  return M.config.cache_path
end

--- Read and validate the cache file. Never raises: a missing, unreadable, or
--- corrupt file (or a schema_version we don't understand) yields `nil` plus a
--- reason string, so callers can render an empty/placeholder state instead of
--- crashing Neovim on startup or on a statusline redraw.
---@return table|nil snapshot
---@return string|nil err
function M.read_cache()
  local path = M.cache_path()
  local stat = vim.uv and vim.uv.fs_stat(path) or vim.loop.fs_stat(path)
  if not stat then
    return nil, "no cache file at " .. path
  end

  local ok_read, lines = pcall(vim.fn.readfile, path)
  if not ok_read then
    return nil, "could not read " .. path
  end

  local content = table.concat(lines, "\n")
  if content == "" then
    return nil, "empty cache file"
  end

  local ok_decode, snapshot = pcall(vim.json.decode, content)
  if not ok_decode or type(snapshot) ~= "table" then
    return nil, "cache file is not valid JSON"
  end

  if snapshot.schema_version ~= SUPPORTED_SCHEMA_VERSION then
    return nil, string.format(
      "unsupported schema_version %s (plugin supports %d)",
      tostring(snapshot.schema_version), SUPPORTED_SCHEMA_VERSION
    )
  end

  return snapshot, nil
end

--- Seconds since `generated_at`, or nil if unknown/unparseable.
function M.stale_seconds(snapshot)
  if not snapshot or not snapshot.generated_at then
    return nil
  end
  -- generated_at is ISO-8601 UTC, e.g. "2026-09-14T12:34:56+00:00". Neovim/Lua has
  -- no builtin ISO-8601 parser; a light manual parse is enough for a health check.
  local y, mo, d, h, mi, s = snapshot.generated_at:match(
    "^(%d+)-(%d+)-(%d+)T(%d+):(%d+):(%d+)"
  )
  if not y then
    return nil
  end
  local generated = os.time({
    year = tonumber(y), month = tonumber(mo), day = tonumber(d),
    hour = tonumber(h), min = tonumber(mi), sec = tonumber(s),
  })
  -- os.time() assumes local time for the table above but generated_at is UTC;
  -- correct for the local UTC offset so the staleness figure is accurate.
  local utc_now = os.time(os.date("!*t"))
  local local_now = os.time(os.date("*t"))
  local offset = local_now - utc_now
  return os.time() - (generated + offset)
end

--- The binding-constraint tool object from the cache, or nil if none/no data.
function M.binding()
  local snapshot = M.read_cache()
  if not snapshot then
    return nil
  end
  return snapshot.binding
end

--- All per-tool entries from the cache, or an empty list if none/no data.
function M.tools()
  local snapshot = M.read_cache()
  if not snapshot or not snapshot.tools then
    return {}
  end
  return snapshot.tools
end

local function pct(x)
  if x == nil then
    return "?"
  end
  return string.format("%.0f%%", x * 100)
end

local function runway(days)
  if days == nil then
    return "n/a"
  end
  if days < 1 then
    return string.format("%.0fh", days * 24)
  end
  return string.format("%.0fd", days)
end

--- Short "CC 61% 2h!" style string for the binding-constraint tool. Empty string
--- (not an error) when there is no cache, no binding, or a stale/unreadable file.
--- Intended as the `lualine` component: `require("token-finops").statusline`.
function M.statusline()
  local snapshot, _err = M.read_cache()
  if not snapshot then
    return ""
  end
  local b = snapshot.binding
  if not b then
    return ""
  end
  return string.format(
    "%s %s %s%s",
    short_name(b.tool), pct(b.used_fraction), runway(b.runway_days), glyph(b.status)
  )
end

--- Render the full per-tool table as a list of plain lines, for the floating
--- window and for anything else that wants readable text instead of raw data.
function M.render_lines()
  local snapshot, err = M.read_cache()
  if not snapshot then
    return { "token-finops: no data (" .. (err or "unknown reason") .. ")",
             "", "Run `token-finops status` once, or start the refresh timer",
             "(see contrib/refresh/) to populate ~/.token-finops/last.json." }
  end

  local lines = {}
  local age = M.stale_seconds(snapshot)
  local age_str = age and string.format("%ds ago", math.floor(age)) or "unknown"
  table.insert(lines, string.format("token-finops — generated %s (%s)", snapshot.generated_at or "?", age_str))
  table.insert(lines, "")

  local header = string.format("%-14s %-6s %-10s %-9s %s", "tool", "used", "runway", "status", "window")
  table.insert(lines, header)
  table.insert(lines, string.rep("-", #header))

  local tools = snapshot.tools or {}
  if #tools == 0 then
    table.insert(lines, "(no tools in cache)")
  end
  for _, t in ipairs(tools) do
    table.insert(lines, string.format(
      "%-14s %-6s %-10s %-9s %s",
      t.display_name or t.tool or "?",
      pct(t.used_fraction),
      runway(t.runway_days),
      t.status or "?",
      t.window or ""
    ))
  end

  table.insert(lines, "")
  local b = snapshot.binding
  if b then
    table.insert(lines, string.format(
      "binding constraint: %s (%s runway, %s)",
      b.display_name or b.tool, runway(b.runway_days), b.status
    ))
  else
    table.insert(lines, "binding constraint: none")
  end

  return lines
end

--- :TokenFinops — a plain floating window with the full per-tool table. No
--- external UI library; vim.api only, per the spec.
function M.open_float()
  local lines = M.render_lines()
  local width = 0
  for _, l in ipairs(lines) do
    width = math.max(width, #l)
  end
  width = math.min(math.max(width + 2, 40), math.floor(vim.o.columns * 0.9))
  local height = math.min(#lines + 1, math.floor(vim.o.lines * 0.8))

  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].modifiable = false
  vim.bo[buf].bufhidden = "wipe"
  vim.bo[buf].filetype = "token-finops"

  local win = vim.api.nvim_open_win(buf, true, {
    relative = "editor",
    width = width,
    height = height,
    row = math.floor((vim.o.lines - height) / 2),
    col = math.floor((vim.o.columns - width) / 2),
    style = "minimal",
    border = "rounded",
    title = " token-finops ",
    title_pos = "center",
  })
  vim.wo[win].wrap = false

  local close = function()
    if vim.api.nvim_win_is_valid(win) then
      vim.api.nvim_win_close(win, true)
    end
  end
  vim.keymap.set("n", "q", close, { buffer = buf, nowait = true, silent = true })
  vim.keymap.set("n", "<Esc>", close, { buffer = buf, nowait = true, silent = true })
end

function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", M.config, opts or {})
end

return M
