#!/usr/bin/env bash
# SwiftBar / xbar plugin: drop into your plugin folder. Refreshes every 5 minutes (filename).
# <xbar.title>token-finops</xbar.title>
# <xbar.version>0.3.0</xbar.version>
# <xbar.desc>Token budget runway across your AI coding agents</xbar.desc>
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
token-finops status --format xbar --max-age 0 2>/dev/null || echo "tokens | color=gray"
