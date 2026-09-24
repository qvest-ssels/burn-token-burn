# token-finops.el

Emacs integration for [`token-finops-cli`](../../token-finops-cli) — a mode-line segment
showing the binding-constraint tool's budget runway, and a `*token-finops*` buffer with the
full per-tool table.

This is the Emacs equivalent of the tmux integration in [`contrib/tmux/`](../tmux/): it is
**read-only against the cache file** (`~/.token-finops/last.json`). It never invokes the
`token-finops` binary and never triggers a rescan — it only reads whatever the cache last had,
kept warm by your own refresh timer (see [`contrib/refresh/`](../refresh/) for cron/systemd/
launchd recipes, or [`docs/TMUX.md`](../../docs/TMUX.md) for the general cache-refresh story).

Not published to MELPA — install manually (see below).

## What it shows

Mode-line segment (`token-finops-mode`), terse like the tmux/starship formats:

```
TF:CC 61% 2h!
```

`CC` short tool name, `61%` used fraction, `2h` runway, `!` status flag (`!` WARN, `!!`
CRITICAL, `X` EXHAUSTED, blank for OK/UNLIMITED, `?` UNKNOWN). Refreshed every
`token-finops-mode-line-interval` seconds (default 45) by re-reading the cache file — never by
shelling out to `token-finops`.

`M-x token-finops-show` (alias `M-x token-finops`) opens a `*token-finops*` buffer
(`tabulated-list-mode`) with every tool's window, used %, runway and status, plus the
`generated_at` timestamp and which tool is the binding constraint. Press `g` in that buffer to
refresh (re-reads the cache file; still never rescans).

If `~/.token-finops/last.json` is missing, corrupt, or has an unrecognised `schema_version`,
both surfaces show a plain "no data yet — run `token-finops status` first" message. This never
signals an Emacs error — a bad cache file cannot disrupt your session.

## Install

No MELPA recipe yet (out of scope for this task — publishing there is a separate,
human/account-owner action). Install manually.

### Plain `load-file`

```elisp
(load-file "~/path/to/burn-token-burn/contrib/emacs/token-finops.el")
(require 'token-finops)
(token-finops-mode 1)
```

### `use-package` with `:load-path`

```elisp
(use-package token-finops
  :load-path "~/path/to/burn-token-burn/contrib/emacs"
  :config
  (token-finops-mode 1))
```

### `use-package` + `straight.el`, pointed at a local checkout

```elisp
(use-package token-finops
  :straight (:local-repo "~/path/to/burn-token-burn/contrib/emacs" :files ("token-finops.el"))
  :config
  (token-finops-mode 1))
```

## Keep the cache warm

This package never rescans. Install one of the refresh timers in
[`contrib/refresh/`](../refresh/) (systemd user timer on Linux, launchd agent on macOS, or a
plain cron line) so `~/.token-finops/last.json` stays current. Without a refresh timer running,
`token-finops-mode` will keep showing whatever was last written — including "no data yet" if
`token-finops status` has never been run at all.

## Customization

```elisp
(setq token-finops-cache-file "~/.token-finops/last.json")  ; default
(setq token-finops-mode-line-interval 45)                   ; seconds between re-reads
(setq token-finops-mode-line-prefix "TF:")                  ; mode-line prefix string
```

Faces `token-finops-ok-face`, `token-finops-warn-face`, `token-finops-critical-face` and
`token-finops-unknown-face` (inheriting `success`/`warning`/`error`/`shadow` by default) style
the `Status` column in the `*token-finops*` buffer — customize them like any other face
(`M-x customize-face`).

## Doom / Spacemacs

Both consume this the same way as vanilla Emacs — it is a plain package, not a Doom module.
Add it via your usual local-package mechanism (e.g. Doom's `packages.el` with
`:recipe (:local-repo "...")`, or `straight.el` as above) and call `(token-finops-mode 1)` from
your config.

## Uninstall / disable

```elisp
(token-finops-mode -1)
```

Cancels the refresh timer and removes the segment from the mode-line; does not touch the cache
file.
