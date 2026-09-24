--- :checkhealth token-finops
---
--- Standard vim.health provider. Checks the cache file only — never invokes the
--- `token-finops` CLI to force a scan; `token-finops` on $PATH is reported as an
--- informational check (the refresh timer, not this plugin, is expected to run it).

local M = {}

local health = vim.health or require("vim.health")
local start = health.start or health.report_start
local ok = health.ok or health.report_ok
local warn = health.warn or health.report_warn
local error_ = health.error or health.report_error
local info = health.info or health.report_info

function M.check()
  start("token-finops.nvim")

  local tf = require("token-finops")
  local path = tf.cache_path()
  info("cache path: " .. path)

  local snapshot, err = tf.read_cache()
  if not snapshot then
    warn("cache unreadable/missing: " .. (err or "unknown reason") ..
      " — run `token-finops status` once, or start the refresh timer (contrib/refresh/)")
  else
    ok("cache parses (schema_version " .. tostring(snapshot.schema_version) .. ")")

    local age = tf.stale_seconds(snapshot)
    local threshold = tf.config.stale_after_seconds
    if age == nil then
      warn("could not determine cache age (unparseable generated_at)")
    elseif age > threshold then
      warn(string.format(
        "cache is %ds old (threshold %ds) — is the refresh timer running? see contrib/refresh/",
        math.floor(age), threshold
      ))
    else
      ok(string.format("cache is fresh (%ds old)", math.floor(age)))
    end

    local n_tools = snapshot.tools and #snapshot.tools or 0
    if n_tools == 0 then
      warn("cache has no tools — no adapter found data on this machine yet")
    else
      ok(n_tools .. " tool(s) in cache")
    end

    if snapshot.binding then
      ok("binding constraint: " .. (snapshot.binding.display_name or snapshot.binding.tool))
    else
      info("no binding constraint (no tool with a bounded runway)")
    end
  end

  -- Informational only: this plugin never shells out to the CLI itself, but the
  -- refresh timer needs `token-finops` on $PATH somewhere, so flag its absence.
  if vim.fn.executable("token-finops") == 1 then
    ok("`token-finops` found on $PATH")
  else
    info("`token-finops` not found on $PATH — fine for this plugin (it only reads the " ..
      "cache), but the refresh timer that keeps the cache warm needs it installed " ..
      "somewhere on the machine running the timer")
  end
end

return M
