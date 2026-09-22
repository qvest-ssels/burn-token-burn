# bash completion for token-finops (token-finops-cli)
#
# Static, hand-maintained: no argcomplete, no runtime import of the package, no build
# step. The drift-guard test token-finops-cli/tests/test_completions.py introspects the
# real argparse tree and fails if a subcommand here goes missing.
#
# Install (pick one):
#   source /path/to/contrib/completions/token-finops.bash   # from ~/.bashrc
#   sudo cp token-finops.bash /etc/bash_completion.d/token-finops
#
# See docs/INSTALL.md for the per-shell instructions.

_token_finops_commands="report sessions self-audit savings break-even collect-statusline
adapters doctor synth status burn cost-per-token"

# --tool choices: the adapter registry (adapters/__init__.py::all_adapters)
_token_finops_tools="aider claude_code cline codex continue copilot gemini_cli hermes opencode"

_token_finops_completions() {
    local cur prev cmd i
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # locate the subcommand (first non-option word after the program name)
    cmd=""
    for ((i = 1; i < COMP_CWORD; i++)); do
        case "${COMP_WORDS[i]}" in
            -*) ;;
            *) cmd="${COMP_WORDS[i]}"; break ;;
        esac
    done

    # value completion for flags that take a constrained argument
    case "$prev" in
        --tool|--tools)
            COMPREPLY=($(compgen -W "$_token_finops_tools" -- "$cur")); return 0 ;;
        --since)
            case "$cmd" in
                burn|cost-per-token) COMPREPLY=($(compgen -W "1d 7d 30d 90d 365d all" -- "$cur")) ;;
                break-even)          COMPREPLY=($(compgen -W "30d 90d all" -- "$cur")) ;;
                *)                   COMPREPLY=($(compgen -W "1d 7d 30d all" -- "$cur")) ;;
            esac
            return 0 ;;
        --format|-f)
            COMPREPLY=($(compgen -W "plain json tmux starship waybar polybar i3 xbar" -- "$cur")); return 0 ;;
        --scenario)
            COMPREPLY=($(compgen -W "steady burst exhausted weekend fresh quiet subagent-heavy" -- "$cur")); return 0 ;;
        --by)
            COMPREPLY=($(compgen -W "day week month" -- "$cur")); return 0 ;;
        --hardware)
            COMPREPLY=($(compgen -W "macbook-pro-16-m4-max-48gb mac-mini-m4-pro-64gb mac-studio-m4-max-128gb mac-studio-m3-ultra-256gb
                rtx-4090-workstation rtx-5090-workstation dgx-spark strix-halo-128gb" -- "$cur")); return 0 ;;
        --model)
            COMPREPLY=($(compgen -W "qwen3-8b qwen3-32b gpt-oss-120b llama-3.3-70b qwen3-235b-a22b" -- "$cur")); return 0 ;;
        --power)
            COMPREPLY=($(compgen -W "grid-de-household solar-de-feed-in solar-de-lcoe grid-us-avg" -- "$cur")); return 0 ;;
        --out|--db-path|--cache-file|--history-file|--config-dir)
            COMPREPLY=($(compgen -f -- "$cur")); return 0 ;;
    esac

    # no subcommand yet -> complete subcommand names (and the top-level flags)
    if [[ -z "$cmd" ]]; then
        COMPREPLY=($(compgen -W "$_token_finops_commands -h --help" -- "$cur"))
        return 0
    fi

    local opts
    case "$cmd" in
        report)  opts="--tool --budget --cycle-day --allowance --compact -c --watch --json --since --db-path --online" ;;
        sessions) opts="--tool --budget --cycle-day --allowance --since --limit --session --gap-minutes --totals --db-path" ;;
        self-audit) opts="--session --config-dir --json" ;;
        savings) opts="--hardware --model --power --utilization --lifetime-years --output-share --own-hardware --co2 --cloud-region --list" ;;
        break-even) opts="--hardware --model --power --lifetime-years --replaceable-tiers --tool --since" ;;
        collect-statusline|adapters) opts="" ;;
        doctor)  opts="--tool --budget --cycle-day --allowance" ;;
        synth)   opts="--out --tools --days --scenario --seed --print-env" ;;
        status)  opts="--format -f --tool --all --fresh --max-age --cache-file --budget --cycle-day --allowance --online" ;;
        burn)    opts="--tool --budget --cycle-day --allowance --since --session --plan --plans --by --history --record --efficiency --nerdy
                       --rate --discount --history-file --json" ;;
        cost-per-token) opts="--tool --budget --cycle-day --allowance --since --json" ;;
        *)       opts="" ;;
    esac
    COMPREPLY=($(compgen -W "$opts -h --help" -- "$cur"))
    return 0
}

complete -F _token_finops_completions token-finops
