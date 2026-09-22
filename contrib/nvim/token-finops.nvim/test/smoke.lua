-- Lightweight sanity check, no test framework: run with
--   nvim --headless -u NONE --noplugin \
--     -c "set rtp+=contrib/nvim/token-finops.nvim" \
--     -c "luafile contrib/nvim/token-finops.nvim/test/smoke.lua" -c "quit"
-- from the repo root. Asserts basic parsing against the synthetic fixture in
-- this directory and against a missing/corrupt-cache path. Exits nonzero on
-- failure so it is usable as a CI gate later if this plugin graduates one.

local script_dir = debug.getinfo(1, "S").source:sub(2):match("(.*/)")
local fixture = script_dir .. "fixture-last.json"

local function fail(msg)
  io.stderr:write("SMOKE FAIL: " .. msg .. "\n")
  vim.cmd("cquit 1")
end

local tf = require("token-finops")

-- 1. Happy path against the synthetic fixture.
tf.setup({ cache_path = fixture })

local snapshot, err = tf.read_cache()
if not snapshot then
  fail("expected fixture to parse, got error: " .. tostring(err))
  return
end
assert(snapshot.schema_version == 1, "schema_version mismatch")
assert(#snapshot.tools == 2, "expected 2 tools in fixture")

local binding = tf.binding()
assert(binding and binding.tool == "claude_code", "expected claude_code as binding tool")

local line = tf.statusline()
assert(line:match("^CC"), "expected statusline to start with short name CC, got: " .. line)
assert(line:match("61%%"), "expected statusline to include used%%, got: " .. line)

local lines = tf.render_lines()
assert(#lines > 3, "expected render_lines to produce a multi-line table")

-- 2. Missing cache file: must not error, must return nil + reason.
tf.setup({ cache_path = script_dir .. "does-not-exist.json" })
local missing_snapshot, missing_err = tf.read_cache()
assert(missing_snapshot == nil, "expected nil snapshot for missing file")
assert(type(missing_err) == "string", "expected a reason string for missing file")
assert(tf.statusline() == "", "expected empty statusline when cache is missing")

-- 3. Corrupt cache file: must not error, must return nil + reason.
local corrupt_path = script_dir .. "corrupt.json"
local fh = io.open(corrupt_path, "w")
fh:write("{ not valid json")
fh:close()
tf.setup({ cache_path = corrupt_path })
local corrupt_snapshot, corrupt_err = tf.read_cache()
os.remove(corrupt_path)
assert(corrupt_snapshot == nil, "expected nil snapshot for corrupt file")
assert(type(corrupt_err) == "string", "expected a reason string for corrupt file")

-- 4. Wrong schema_version: must not error, must return nil + reason.
local wrong_schema_path = script_dir .. "wrong-schema.json"
local fh2 = io.open(wrong_schema_path, "w")
fh2:write('{"schema_version": 999, "generated_at": "2026-01-01T00:00:00+00:00", "tools": [], "binding": null}')
fh2:close()
tf.setup({ cache_path = wrong_schema_path })
local wrong_snapshot, wrong_err = tf.read_cache()
os.remove(wrong_schema_path)
assert(wrong_snapshot == nil, "expected nil snapshot for unsupported schema_version")
assert(wrong_err:match("schema_version"), "expected schema_version mention in error, got: " .. tostring(wrong_err))

print("SMOKE OK: all token-finops.nvim assertions passed")
