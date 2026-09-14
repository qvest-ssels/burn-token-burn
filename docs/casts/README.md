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
| `06-install-pip.cast` | first-time install from PyPI: `pip install token-finops-cli`, `pip show`, `which`, `sessions --help` |

## `06-install-pip.cast` is the odd one out: a real install, not synthetic data

Unlike `01`–`05`, this cast uses **no** `synth` data. It is an unedited recording of `pip install
token-finops-cli` against the live PyPI index — proof that the published package installs and that
the `token-finops` entry point lands on `$PATH`. The install happens inside a throwaway virtualenv
so the recording host's real environment is never touched, but venv setup itself isn't part of the
visible recording (it starts right at `pip install`) and the venv's real path is sanitized to a
literal `~` (tilde), as if it were a real user's home directory, rather than leaking a real
machine's `/tmp` path or username.

Note what it shows honestly: PyPI currently serves **0.2.0**, the original Copilot-only single-file
tool. The 9-adapter `report` / `adapters` / `self-audit` CLI in this repository is 0.3.x and is not
released yet, which is why the cast demonstrates `sessions --help` rather than `adapters`. Re-record
this cast after the next PyPI release so it reflects the current CLI.

Re-record it with (`./tmp/` is repo-local and gitignored — see `AGENTS.md`'s "no system `/tmp`"
rule — used so scratch state from recording never leaks outside the repo, and never touches the
real system `/tmp`):

```bash
mkdir -p tmp && rm -rf tmp/token-finops-venv
python3 -m venv tmp/token-finops-venv
cat > tmp/tf-demo.sh <<'SH'
source tmp/token-finops-venv/bin/activate
P=$'\033[1;32m$ \033[0m'
run() { printf '%s%s\n' "$P" "$1"; eval "$1"; echo; sleep 1.2; }
run 'pip install token-finops-cli'
run 'pip show token-finops-cli'
run 'which token-finops'
run 'token-finops sessions --help'
SH
PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 TERM=linux \
  asciinema rec docs/casts/06-install-pip.cast --overwrite --headless \
    --window-size 110x40 --output-format asciicast-v2 -i 2 \
    -t 'token-finops: 06-install-pip' -c 'bash tmp/tf-demo.sh'
rm -rf tmp/token-finops-venv tmp/tf-demo.sh
# sanitize the throwaway venv's real absolute path to "~/token-finops-venv"
python3 -c "
path = 'docs/casts/06-install-pip.cast'
content = open(path, encoding='utf-8').read()
content = content.replace('$(pwd)/tmp/token-finops-venv', '~/token-finops-venv')
open(path, 'w', encoding='utf-8').write(content)
"
```

Re-record after CLI changes (same `./tmp/` convention, sanitized to `~/casthome` afterward):

```bash
mkdir -p tmp && uv run token-finops synth --out tmp/casthome --scenario burst --print-env > tmp/cast.env
eval "$(grep ^export tmp/cast.env)"; export HOME="$(pwd)/tmp/casthome"
asciinema rec -c 'token-finops report --compact --budget 20000' docs/casts/01-report.cast --overwrite
python3 -c "
path = 'docs/casts/01-report.cast'
content = open(path, encoding='utf-8').read()
content = content.replace('$(pwd)/tmp/casthome', '~/casthome')
open(path, 'w', encoding='utf-8').write(content)
"
rm -rf tmp/casthome tmp/cast.env
```

Recordings are plain JSON (asciicast v2); keep them small and commit them — they double as a
human-readable snapshot of the CLI's output at a given version.
