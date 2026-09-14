# Terminal recordings (asciinema)

Casts `01`–`05` are recorded against `token-finops synth --scenario burst` data, so numbers are
synthetic but every command is real. Play locally with `asciinema play <file>` or upload with
`asciinema upload <file>` to embed on asciinema.org / in the README.

| Cast | Shows |
|---|---|
| `01-report.cast` | `adapters`, `report --compact`, full Copilot report with runway |
| `02-status-formats.cast` | `status` in plain, tmux, starship and waybar formats (cache + `--fresh`) |
| `03-self-audit.cast` | `self-audit` on a Claude Code session with sub-agents on Sonnet and Haiku |
| `04-savings-break-even.cast` | Mac Studio at 20 % vs 80 % utilisation, solar tariff, break-even replay |
| `05-synth.cast` | generating a fake home and the `--print-env` one-liner |
| `06-install-pip.cast` | first-time install from PyPI into a fresh venv: `pip install token-finops-cli`, `pip show`, `which`, `sessions --help` |

## `06-install-pip.cast` is the odd one out: a real install, not synthetic data

Unlike `01`–`05`, this cast uses **no** `synth` data and no fake `$HOME`. It is an unedited
recording of a first-time user creating an empty virtualenv and running `pip install
token-finops-cli` against the live PyPI index — proof that the published package installs and that
the `token-finops` entry point lands on `$PATH`. The venv is thrown away right after recording.

Note what it shows honestly: PyPI currently serves **0.2.0**, the original Copilot-only single-file
tool. The 9-adapter `report` / `adapters` / `self-audit` CLI in this repository is 0.3.x and is not
released yet, which is why the cast demonstrates `sessions --help` rather than `adapters`. Re-record
this cast after the next PyPI release so it reflects the current CLI.

Re-record it with:

```bash
rm -rf /tmp/tf-install-demo
cat > /tmp/tf-demo.sh <<'SH'
P=$'\033[1;32m$ \033[0m'
run() { printf '%s%s\n' "$P" "$1"; eval "$1"; echo; sleep 1.2; }
run 'python3 -m venv /tmp/tf-install-demo'
run 'source /tmp/tf-install-demo/bin/activate'
run 'pip install token-finops-cli'
run 'pip show token-finops-cli'
run 'which token-finops'
run 'token-finops sessions --help'
SH
PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 TERM=linux \
  asciinema rec docs/casts/06-install-pip.cast --overwrite --headless \
    --window-size 110x40 --output-format asciicast-v2 -i 2 \
    -t 'token-finops: 06-install-pip' -c 'bash /tmp/tf-demo.sh'
rm -rf /tmp/tf-install-demo /tmp/tf-demo.sh
```

Re-record after CLI changes:

```bash
uv run token-finops synth --out /tmp/casthome --scenario burst --print-env > /tmp/cast.env
eval "$(grep ^export /tmp/cast.env)"; export HOME=/tmp/casthome
asciinema rec -c 'token-finops report --compact --budget 20000' docs/casts/01-report.cast --overwrite
```

Recordings are plain JSON (asciicast v2); keep them small and commit them — they double as a
human-readable snapshot of the CLI's output at a given version.
