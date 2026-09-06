#!/usr/bin/env bash
# token-finops tmux plugin — shows the binding token runway in status-right.
# Install with TPM:   set -g @plugin 'tronicum/burn-token-burn'   (path: contrib/tmux)
# or manually:        run-shell ~/path/to/contrib/tmux/token-finops.tmux
#
# Options (set in .tmux.conf before running the plugin):
#   set -g @token_finops_format  'tmux'     # tmux|plain|starship
#   set -g @token_finops_interval 60        # tmux status-interval to use
#   set -g @token_finops_bin 'token-finops' # binary/uv wrapper to call
set -euo pipefail

get_opt() { tmux show-option -gqv "$1"; }

fmt="$(get_opt @token_finops_format)";     fmt="${fmt:-tmux}"
interval="$(get_opt @token_finops_interval)"; interval="${interval:-60}"
bin="$(get_opt @token_finops_bin)";        bin="${bin:-token-finops}"

# The segment reads the cache written by `token-finops status` (refreshed by a
# timer, see contrib/refresh) so tmux never triggers a rescan on every redraw.
segment="#(${bin} status --format ${fmt} --max-age 0 2>/dev/null || cat ~/.token-finops/last-line.txt 2>/dev/null)"

tmux set-option -g status-interval "${interval}"
current="$(get_opt status-right)"
case "${current}" in
  *token-finops*|*token_finops*) ;;   # already installed
  *) tmux set-option -g status-right "${segment} ${current}" ;;
esac
