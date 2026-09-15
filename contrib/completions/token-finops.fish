# fish completion for token-finops (token-finops-cli)
#
# Static, hand-maintained: no argcomplete, no runtime import of the package, no build
# step. The drift-guard test token-finops-cli/tests/test_completions.py introspects the
# real argparse tree and fails if a subcommand here goes missing.
#
# Install:
#   cp token-finops.fish ~/.config/fish/completions/token-finops.fish
#
# See docs/INSTALL.md for the per-shell instructions.

# Only offer subcommand names while no subcommand has been given yet.
function __fish_token_finops_no_subcommand
    set -l cmd (commandline -opc)
    set -e cmd[1]
    for i in $cmd
        switch $i
            case '-*'
                continue
            case '*'
                return 1
        end
    end
    return 0
end

# --tool choices: the adapter registry (adapters/__init__.py::all_adapters)
set -l __tf_tools aider claude_code cline codex continue copilot gemini_cli hermes opencode
set -l __tf_hardware mac-mini-m4-pro-64gb mac-studio-m4-max-128gb mac-studio-m3-ultra-256gb rtx-4090-workstation rtx-5090-workstation dgx-spark strix-halo-128gb
set -l __tf_models qwen3-8b qwen3-32b gpt-oss-120b llama-3.3-70b qwen3-235b-a22b
set -l __tf_power grid-de-household solar-de-feed-in solar-de-lcoe grid-us-avg

# no file completion anywhere unless a flag explicitly asks for it
complete -c token-finops -f

# ----------------------------------------------------------------- subcommands
complete -c token-finops -n __fish_token_finops_no_subcommand -a report -d 'usage summary + runway per tool (default)'
complete -c token-finops -n __fish_token_finops_no_subcommand -a sessions -d 'per-session table'
complete -c token-finops -n __fish_token_finops_no_subcommand -a self-audit -d 'Claude Code: cost of one session, incl. sub-agents'
complete -c token-finops -n __fish_token_finops_no_subcommand -a savings -d 'local $/MTok vs cloud tier'
complete -c token-finops -n __fish_token_finops_no_subcommand -a break-even -d 'when would a local box have paid off?'
complete -c token-finops -n __fish_token_finops_no_subcommand -a collect-statusline -d 'Claude Code statusLine hook'
complete -c token-finops -n __fish_token_finops_no_subcommand -a adapters -d 'list detected data sources'
complete -c token-finops -n __fish_token_finops_no_subcommand -a doctor -d 'diagnose empty reports per tool'
complete -c token-finops -n __fish_token_finops_no_subcommand -a synth -d 'write a synthetic fake-home tree'
complete -c token-finops -n __fish_token_finops_no_subcommand -a status -d 'one-line status for tmux/starship/waybar'
complete -c token-finops -n __fish_token_finops_no_subcommand -a burn -d 'plan equivalents and burn efficiency'
complete -c token-finops -n __fish_token_finops_no_subcommand -a cost-per-token -d '$/1M tokens by model'

complete -c token-finops -s h -l help -d 'show help and exit'

# ----------------------------------------------------------------- report
complete -c token-finops -n '__fish_seen_subcommand_from report' -l tool -x -a "$__tf_tools" -d 'restrict to tool(s)'
complete -c token-finops -n '__fish_seen_subcommand_from report' -l budget -x -d 'Copilot monthly AI-unit allowance'
complete -c token-finops -n '__fish_seen_subcommand_from report' -l cycle-day -x -d 'Copilot cycle reset day (UTC)'
complete -c token-finops -n '__fish_seen_subcommand_from report' -l allowance -x -d 'allowance for non-Copilot tools'
complete -c token-finops -n '__fish_seen_subcommand_from report' -s c -l compact -d 'one line per tool'
complete -c token-finops -n '__fish_seen_subcommand_from report' -l watch -x -d 'refresh every N seconds'
complete -c token-finops -n '__fish_seen_subcommand_from report' -l json -d 'machine-readable output'
complete -c token-finops -n '__fish_seen_subcommand_from report' -l since -x -a '1d 7d 30d all' -d 'usage summary window'
complete -c token-finops -n '__fish_seen_subcommand_from report' -l db-path -r -F -d 'Copilot session-store.db'

# ----------------------------------------------------------------- sessions
complete -c token-finops -n '__fish_seen_subcommand_from sessions' -l tool -x -a "$__tf_tools" -d 'restrict to tool(s)'
complete -c token-finops -n '__fish_seen_subcommand_from sessions' -l since -x -a '1d 7d 30d all' -d 'window'
complete -c token-finops -n '__fish_seen_subcommand_from sessions' -l limit -x -d 'max sessions to list'
complete -c token-finops -n '__fish_seen_subcommand_from sessions' -l session -x -d 'Copilot: break/gap report for one session_id'
complete -c token-finops -n '__fish_seen_subcommand_from sessions' -l gap-minutes -x -d 'idle gap that counts as a break'
complete -c token-finops -n '__fish_seen_subcommand_from sessions' -l totals -d 'one combined report across ALL sessions'
complete -c token-finops -n '__fish_seen_subcommand_from sessions' -l db-path -r -F -d 'Copilot session-store.db'

# ----------------------------------------------------------------- self-audit
complete -c token-finops -n '__fish_seen_subcommand_from self-audit' -l session -x -a latest -d "session id prefix or 'latest'"
complete -c token-finops -n '__fish_seen_subcommand_from self-audit' -l config-dir -r -F -d 'Claude Code config dir'
complete -c token-finops -n '__fish_seen_subcommand_from self-audit' -l json -d 'machine-readable output'

# ----------------------------------------------------------------- savings
complete -c token-finops -n '__fish_seen_subcommand_from savings break-even' -l hardware -x -a "$__tf_hardware" -d 'hardware profile key'
complete -c token-finops -n '__fish_seen_subcommand_from savings break-even' -l model -x -a "$__tf_models" -d 'local model key'
complete -c token-finops -n '__fish_seen_subcommand_from savings break-even' -l power -x -a "$__tf_power" -d 'tariff key from energy.json'
complete -c token-finops -n '__fish_seen_subcommand_from savings break-even' -l lifetime-years -x -d 'amortisation lifetime'
complete -c token-finops -n '__fish_seen_subcommand_from savings' -l utilization -x -d 'fraction of 24/7 actually inferring'
complete -c token-finops -n '__fish_seen_subcommand_from savings' -l output-share -x -d 'share of output tokens in the cloud blend'
complete -c token-finops -n '__fish_seen_subcommand_from savings' -l list -d 'list hardware/model/tariff keys'

# ----------------------------------------------------------------- break-even
complete -c token-finops -n '__fish_seen_subcommand_from break-even' -l replaceable-tiers -x -d 'cloud tiers a local model could replace'
complete -c token-finops -n '__fish_seen_subcommand_from break-even' -l tool -x -a "$__tf_tools" -d 'restrict to tool(s)'
complete -c token-finops -n '__fish_seen_subcommand_from break-even' -l since -x -a '30d 90d all' -d 'window'

# ----------------------------------------------------------------- doctor
complete -c token-finops -n '__fish_seen_subcommand_from doctor' -l tool -x -a "$__tf_tools" -d 'restrict the diagnosis to tool(s)'

# ----------------------------------------------------------------- synth
complete -c token-finops -n '__fish_seen_subcommand_from synth' -l out -r -F -d 'output directory'
complete -c token-finops -n '__fish_seen_subcommand_from synth' -l tools -x -a "$__tf_tools" -d 'comma-separated tool(s) to generate'
complete -c token-finops -n '__fish_seen_subcommand_from synth' -l days -x -d 'how many days of history'
complete -c token-finops -n '__fish_seen_subcommand_from synth' -l scenario -x -a 'steady burst exhausted weekend fresh quiet subagent-heavy' -d 'burn profile'
complete -c token-finops -n '__fish_seen_subcommand_from synth' -l seed -x -d 'RNG seed'
complete -c token-finops -n '__fish_seen_subcommand_from synth' -l print-env -d 'also print export VAR=... lines'

# ----------------------------------------------------------------- status
complete -c token-finops -n '__fish_seen_subcommand_from status' -s f -l format -x -a 'plain json tmux starship waybar polybar i3 xbar' -d 'renderer'
complete -c token-finops -n '__fish_seen_subcommand_from status' -l tool -x -a "$__tf_tools" -d 'restrict to tool(s)'
complete -c token-finops -n '__fish_seen_subcommand_from status' -l all -d 'include UNLIMITED (usage-only) tools'
complete -c token-finops -n '__fish_seen_subcommand_from status' -l fresh -d 'rescan telemetry now and refresh the cache'
complete -c token-finops -n '__fish_seen_subcommand_from status' -l max-age -x -d 'cache max age in seconds'
complete -c token-finops -n '__fish_seen_subcommand_from status' -l cache-file -r -F -d 'override ~/.token-finops/last.json'
complete -c token-finops -n '__fish_seen_subcommand_from status' -l budget -x -d 'Copilot allowance for a fresh scan'
complete -c token-finops -n '__fish_seen_subcommand_from status' -l cycle-day -x -d 'Copilot cycle reset day'
complete -c token-finops -n '__fish_seen_subcommand_from status' -l allowance -x -d 'allowance for non-Copilot tools'

# ----------------------------------------------------------------- burn
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l tool -x -a "$__tf_tools" -d 'restrict to tool(s)'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l since -x -a '1d 7d 30d 90d 365d all' -d 'window'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l session -x -d 'Claude Code: one session id prefix'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l plan -x -d 'your plan id, e.g. claude:max-20x'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l plans -d 'list the plan catalogue and exit'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l by -x -a 'day week month' -d 'bucket the table'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l history -d 'use the recorded history file'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l record -d "append today's totals to the history file"
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l efficiency -l nerdy -d 'burn efficiency breakdown'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l rate -x -d 'IN/OUT[/CR[/CW]] price override'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l discount -x -d 'discount fraction'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l history-file -r -F -d 'override ~/.token-finops/history.jsonl'
complete -c token-finops -n '__fish_seen_subcommand_from burn' -l json -d 'machine-readable output'

# ----------------------------------------------------------------- cost-per-token
complete -c token-finops -n '__fish_seen_subcommand_from cost-per-token' -l tool -x -a "$__tf_tools" -d 'restrict to tool(s)'
complete -c token-finops -n '__fish_seen_subcommand_from cost-per-token' -l since -x -a '1d 7d 30d 90d 365d all' -d 'window'
complete -c token-finops -n '__fish_seen_subcommand_from cost-per-token' -l json -d 'machine-readable output'
