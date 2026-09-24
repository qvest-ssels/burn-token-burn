#compdef token-finops
#
# zsh completion for token-finops (token-finops-cli)
#
# Static, hand-maintained: no argcomplete, no runtime import of the package, no build
# step. The drift-guard test token-finops-cli/tests/test_completions.py introspects the
# real argparse tree and fails if a subcommand here goes missing.
#
# Install: put this file somewhere on your $fpath as `_token-finops`, e.g.
#   mkdir -p ~/.zsh/completions
#   cp token-finops.zsh ~/.zsh/completions/_token-finops
#   # in ~/.zshrc, before compinit:
#   fpath=(~/.zsh/completions $fpath)
#   autoload -Uz compinit && compinit
#
# See docs/INSTALL.md for the per-shell instructions.

_token_finops_tool_arg() {
    # --tool choices: the adapter registry (adapters/__init__.py::all_adapters)
    local -a tools
    tools=(aider claude_code cline codex continue copilot gemini_cli hermes opencode)
    _values -s , 'tool' $tools
}

_token-finops() {
    local curcontext="$curcontext" state line
    typeset -A opt_args

    local -a commands
    commands=(
        'report:usage summary + runway per tool (default)'
        'sessions:per-session table (Copilot: --session/--totals break reports)'
        'self-audit:Claude Code: what did one session cost, incl. sub-agents'
        'savings:local $/MTok vs cloud tier for a hardware+model combo'
        'break-even:from your real usage: when would a local box have paid off?'
        'collect-statusline:Claude Code statusLine hook: persist rate_limits'
        'adapters:list detected data sources'
        'doctor:diagnose empty reports: per tool found/empty/missing + what to do next'
        'synth:write a synthetic fake-home tree for offline demos/tests'
        'status:one-line status for tmux/starship/waybar/…'
        'burn:plan equivalents, weekly/monthly tables, burn efficiency'
        'cost-per-token:$/1M tokens by model'
    )

    _arguments -C \
        '(-h --help)'{-h,--help}'[show help and exit]' \
        '1: :->command' \
        '*:: :->args' && return 0

    case $state in
        command)
            _describe -t commands 'token-finops command' commands && return 0
            ;;
        args)
            case $words[1] in
                report)
                    _arguments \
                        '*--tool=[restrict to tool(s)]:tool:_token_finops_tool_arg' \
                        '--budget=[Copilot monthly AI-unit allowance]:units:' \
                        '--cycle-day=[Copilot cycle reset day (UTC)]:day:' \
                        '--allowance=[allowance for non-Copilot tools]:units:' \
                        '(-c --compact)'{-c,--compact}'[one line per tool]' \
                        '--watch=[refresh every N seconds]:seconds:' \
                        '--json[machine-readable output]' \
                        '--since=[usage summary window]:window:(1d 7d 30d all)' \
                        '--db-path=[Copilot session-store.db to read]:file:_files' \
                        '--online[opt-in: live provider quota, cached 180s, offline fallback]' \
                        '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
                sessions)
                    _arguments \
                        '--budget=[Copilot monthly AI-unit allowance]:units:' \
                        '--cycle-day=[monthly cycle reset day (UTC)]:day:' \
                        '--allowance=[allowance for non-Copilot tools]:units:' \
                        '*--tool=[restrict to tool(s)]:tool:_token_finops_tool_arg' \
                        '--since=[window]:window:(1d 7d 30d all)' \
                        '--limit=[max sessions to list]:n:' \
                        '--session=[Copilot: break/gap report for one session_id]:session id:' \
                        '--gap-minutes=[idle gap that counts as a break]:minutes:' \
                        '--totals[one combined report across ALL sessions]' \
                        '--db-path=[Copilot session-store.db to read]:file:_files' \
                        '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
                self-audit)
                    _arguments \
                        "--session=[session id prefix or 'latest']:session:(latest)" \
                        '--config-dir=[Claude Code config dir]:directory:_files -/' \
                        '--json[machine-readable output]' \
                        '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
                savings)
                    _arguments \
                        '--hardware=[hardware profile key]:hardware:(macbook-pro-16-m4-max-48gb mac-mini-m4-pro-64gb mac-studio-m4-max-128gb mac-studio-m3-ultra-256gb rtx-4090-workstation rtx-5090-workstation dgx-spark strix-halo-128gb)' \
                        '--model=[local model key]:model:(qwen3-8b qwen3-32b gpt-oss-120b llama-3.3-70b qwen3-235b-a22b)' \
                        '--power=[tariff key from energy.json]:tariff:(grid-de-household solar-de-feed-in solar-de-lcoe grid-us-avg)' \
                        '--utilization=[fraction of 24/7 actually inferring]:fraction:' \
                        '--lifetime-years=[amortisation lifetime]:years:' \
                        '--output-share=[share of output tokens in the cloud blend]:fraction:' \
                        '--own-hardware[you already own the box: energy-only, capex is sunk]' \
                        '--co2[green-IT block: local vs ESTIMATED cloud gCO2/1M tok]' \
                        '--cloud-region=[grid region for the cloud CO2 estimate]:region:(us-avg us-virginia us-ercot de-grid)' \
                        '--list[list hardware/model/tariff keys]' \
                        '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
                break-even)
                    _arguments \
                        '--hardware=[hardware profile key]:hardware:(macbook-pro-16-m4-max-48gb mac-mini-m4-pro-64gb mac-studio-m4-max-128gb mac-studio-m3-ultra-256gb rtx-4090-workstation rtx-5090-workstation dgx-spark strix-halo-128gb)' \
                        '--model=[local model key]:model:(qwen3-8b qwen3-32b gpt-oss-120b llama-3.3-70b qwen3-235b-a22b)' \
                        '--power=[tariff key from energy.json]:tariff:(grid-de-household solar-de-feed-in solar-de-lcoe grid-us-avg)' \
                        '--lifetime-years=[amortisation lifetime]:years:' \
                        '--replaceable-tiers=[cloud tiers a local model could replace]:tiers:' \
                        '*--tool=[restrict to tool(s)]:tool:_token_finops_tool_arg' \
                        '--since=[window]:window:(30d 90d all)' \
                        '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
                collect-statusline|adapters)
                    _arguments '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
                doctor)
                    _arguments \
                        '--budget=[Copilot monthly AI-unit allowance]:units:' \
                        '--cycle-day=[monthly cycle reset day (UTC)]:day:' \
                        '--allowance=[allowance for non-Copilot tools]:units:' \
                        '*--tool=[restrict the diagnosis to tool(s)]:tool:_token_finops_tool_arg' \
                        '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
                synth)
                    _arguments \
                        '--out=[output directory]:directory:_files -/' \
                        '*--tools=[comma-separated tool(s) to generate]:tool:_token_finops_tool_arg' \
                        '--days=[how many days of history]:days:' \
                        '--scenario=[burn profile]:scenario:(steady burst exhausted weekend fresh quiet subagent-heavy)' \
                        '--seed=[RNG seed]:seed:' \
                        '--print-env[also print export VAR=... lines]' \
                        '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
                status)
                    _arguments \
                        '(-f --format)'{-f,--format}'=[renderer]:format:(plain json tmux starship waybar polybar i3 xbar)' \
                        '*--tool=[restrict to tool(s)]:tool:_token_finops_tool_arg' \
                        '--all[include UNLIMITED (usage-only) tools]' \
                        '--fresh[rescan telemetry now and refresh the cache]' \
                        '--max-age=[cache max age]:seconds:' \
                        '--cache-file=[override ~/.token-finops/last.json]:file:_files' \
                        '--budget=[Copilot allowance for a fresh scan]:units:' \
                        '--cycle-day=[Copilot cycle reset day]:day:' \
                        '--allowance=[allowance for non-Copilot tools]:units:' \
                        '--online[opt-in: live provider quota, implies a rescan]' \
                        '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
                burn)
                    _arguments \
                        '--budget=[Copilot monthly AI-unit allowance]:units:' \
                        '--cycle-day=[monthly cycle reset day (UTC)]:day:' \
                        '--allowance=[allowance for non-Copilot tools]:units:' \
                        '*--tool=[restrict to tool(s)]:tool:_token_finops_tool_arg' \
                        '--since=[window]:window:(1d 7d 30d 90d 365d all)' \
                        '--session=[Claude Code: one session id prefix]:session:' \
                        '--plan=[your plan id, e.g. claude:max-20x]:plan:' \
                        '--plans[list the plan catalogue and exit]' \
                        '--by=[bucket the table]:bucket:(day week month)' \
                        '--history[use the recorded history file]' \
                        '--record[append todays totals to the history file]' \
                        '(--efficiency --nerdy)'{--efficiency,--nerdy}'[burn efficiency breakdown]' \
                        '--rate=[IN/OUT[/CR[/CW]] price override]:rate:' \
                        '--discount=[discount fraction]:fraction:' \
                        '--history-file=[override ~/.token-finops/history.jsonl]:file:_files' \
                        '--json[machine-readable output]' \
                        '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
                cost-per-token)
                    _arguments \
                        '--budget=[Copilot monthly AI-unit allowance]:units:' \
                        '--cycle-day=[monthly cycle reset day (UTC)]:day:' \
                        '--allowance=[allowance for non-Copilot tools]:units:' \
                        '*--tool=[restrict to tool(s)]:tool:_token_finops_tool_arg' \
                        '--since=[window]:window:(1d 7d 30d 90d 365d all)' \
                        '--json[machine-readable output]' \
                        '(-h --help)'{-h,--help}'[show help and exit]'
                    ;;
            esac
            ;;
    esac
}

_token-finops "$@"
