# Terminal recordings (asciinema)

Recorded against `token-finops synth --scenario burst` data, so numbers are synthetic but every
command is real. Play locally with `asciinema play <file>` or upload with `asciinema upload <file>`
to embed on asciinema.org / in the README.

| Cast | Shows |
|---|---|
| `01-report.cast` | `adapters`, `report --compact`, full Copilot report with runway |
| `02-status-formats.cast` | `status` in plain, tmux, starship and waybar formats (cache + `--fresh`) |
| `03-self-audit.cast` | `self-audit` on a Claude Code session with sub-agents on Sonnet and Haiku |
| `04-savings-break-even.cast` | Mac Studio at 20 % vs 80 % utilisation, solar tariff, break-even replay |
| `05-synth.cast` | generating a fake home and the `--print-env` one-liner |

Re-record after CLI changes:

```bash
uv run token-finops synth --out /tmp/casthome --scenario burst --print-env > /tmp/cast.env
eval "$(grep ^export /tmp/cast.env)"; export HOME=/tmp/casthome
asciinema rec -c 'token-finops report --compact --budget 20000' docs/casts/01-report.cast --overwrite
```

Recordings are plain JSON (asciicast v2); keep them small and commit them — they double as a
human-readable snapshot of the CLI's output at a given version.
