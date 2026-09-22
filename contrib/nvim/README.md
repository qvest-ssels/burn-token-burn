# token-finops.nvim — Neovim integration

A small, standalone Neovim plugin under `token-finops.nvim/` that surfaces the
`token-finops` runway inside Neovim: a statusline segment, a `:TokenFinops`
floating window, and a `:checkhealth token-finops` provider.

Same pattern as the tmux integration in `../tmux/`: this plugin is a **cache
reader, never a rescanner**. It reads `~/.token-finops/last.json` — the file
`token-finops status` writes — and does nothing at all if that file is
missing, stale, or corrupt (no error, just an empty/placeholder state). Keep
the cache warm with **one** refresh timer (see `../refresh/README.md`,
systemd user timer / launchd agent / cron); every widget, tmux segment, and
this plugin then just poll that same cache as often as they like.

## File layout

```
contrib/nvim/token-finops.nvim/
  lua/token-finops/init.lua     core: read/validate the cache, statusline(), render_lines(), open_float()
  lua/token-finops/health.lua   :checkhealth token-finops provider
  plugin/token-finops.lua       auto-loaded: defines :TokenFinops, registers health check
  doc/token-finops.txt          :help token-finops
  test/fixture-last.json        synthetic cache fixture for the smoke check
  test/smoke.lua                headless sanity check (see "Verifying" below)
```

## Install

**lazy.nvim**, from a local checkout of this repo:

```lua
{
  dir = "~/workspace/burn-token-burn/contrib/nvim/token-finops.nvim",
  name = "token-finops.nvim",
  config = function()
    require("token-finops").setup({})
  end,
}
```

Or, once this plugin has its own git history worth pointing at (see
`docs/INTEGRATIONS.md` §5.5 — it is filed as a "first-party, separate
release" item, not a `contrib/`-tested one), the usual GitHub-shorthand form:

```lua
{ "qvest-ssels/token-finops.nvim", config = function() require("token-finops").setup({}) end }
```

**packer.nvim**:

```lua
use({
  "~/workspace/burn-token-burn/contrib/nvim/token-finops.nvim",
  config = function() require("token-finops").setup({}) end,
})
```

**Native `:h packages`** (no plugin manager): symlink or clone the
`token-finops.nvim/` directory into `~/.config/nvim/pack/*/start/`.

LazyVim / AstroNvim / LunarVim / NvChad need nothing extra — they are Neovim
configurations, not separate ecosystems; add the plugin spec above to
whichever file that distribution uses for user plugins (docs/INTEGRATIONS.md
§2 makes this point explicitly to avoid four fake "integrations").

## Refresh timer (populate the cache)

This plugin **never** runs `token-finops` itself. Something else has to keep
`~/.token-finops/last.json` warm — the same timer every other surface in
`contrib/` already uses:

```bash
# see contrib/refresh/README.md for the full recipe
mkdir -p ~/.config/systemd/user
cp ../refresh/token-finops-refresh.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now token-finops-refresh.timer
```

or on macOS, `launchctl load ../refresh/com.tronicum.token-finops.refresh.plist`,
or a two-minute cron entry (`*/2 * * * * token-finops status --fresh >/dev/null`).
Without a timer running, the cache simply ages — `:checkhealth token-finops`
will tell you if it has gone stale.

## Statusline

**lualine.nvim** (primary target):

```lua
require("lualine").setup({
  sections = {
    lualine_x = { require("token-finops").statusline, "encoding", "fileformat" },
  },
})
```

`statusline()` returns a short string for the *binding-constraint* tool only
(the one that runs out first), e.g. `"CC 61% 2h!"` — short name, used%,
runway, status glyph — matching `token_finops_cli/status.py`'s `SHORT`/`GLYPH`
maps for visual consistency with the tmux/waybar/xbar segments. It returns
`""` (not an error) whenever there is no usable cache, so an empty lualine
component just renders nothing.

**heirline.nvim** is not separately implemented here — `require("token-finops").statusline()`
is a plain function returning a plain string, so a heirline component is a
one-liner:

```lua
{
  provider = function()
    return require("token-finops").statusline()
  end,
}
```

No dedicated heirline component/stub is shipped beyond that snippet because
the lualine component already exercises all the logic (heirline's `provider`
just wants the same function); duplicating it as a second "component" would
be a distinction without a difference.

## `:TokenFinops`

Opens a floating window (plain `vim.api`, no external UI-library dependency)
with the full per-tool table — tool, used%, runway, status, window — plus the
cache's `generated_at` timestamp and age, and which tool is the binding
constraint. Press `q` or `<Esc>` to close.

## Health check

`:checkhealth token-finops` verifies:

- the cache file exists and is readable
- it parses as JSON with a supported `schema_version`
- how stale it is, against a configurable threshold (`stale_after_seconds`,
  default 600s — the refresh timers in `../refresh/` run every 60-300s, so
  anything past 600s usually means the timer stopped)
- whether `token-finops` is on `$PATH` (**informational only** — this plugin
  doesn't need it; the machine running the refresh timer does)

## Verifying the Lua

No Lua test framework exists in this repo (Python's pytest rigor is
`token-finops-cli`'s, not this plugin's) — a small headless script is the
bar instead:

```bash
nvim --headless -u NONE --noplugin \
  -c "set rtp+=$(pwd)/contrib/nvim/token-finops.nvim" \
  -c "luafile $(pwd)/contrib/nvim/token-finops.nvim/test/smoke.lua" -c "quit"
```

It loads the module, points it at `test/fixture-last.json`, and asserts:
parsing succeeds and yields the expected binding tool; a missing cache file
returns `nil` + a reason (no error); a corrupt (non-JSON) cache file returns
`nil` + a reason (no error); and an unsupported `schema_version` is rejected
by name. Exits nonzero (`cquit 1`) on any assertion failure.

## Config path

`token_finops_cli/status.py` has no environment-variable override for the
cache path today — only a `--cache-file` flag on `token-finops status`
itself, which a background timer would use, not this plugin. So the honest
default here is the same hardcoded path every other `contrib/` integration
uses, `~/.token-finops/last.json` (via `vim.fn.expand("~")`). For local
experiments this plugin additionally honours `$TOKEN_FINOPS_CACHE` and a
`setup({ cache_path = ... })` override — both are conventions of *this
plugin*, not something the CLI itself reads, and are documented as such so
nobody assumes setting the env var changes what the CLI writes.
