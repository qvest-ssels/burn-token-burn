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
| `06-install-pip.cast` | first-time install from PyPI: `pip install token-finops-cli`, `pip show`, `which`, `adapters` |
| `07-doctor.cast` | `doctor` on a machine with two tools installed and seven missing — the found/missing tiers and one hint each |
| `08-savings-co2.cast` | `savings --co2` against two cloud grids: the `[computed]` local figure vs. the `[ESTIMATE]` cloud one |

## `06-install-pip.cast` is the odd one out: a real install, not synthetic data

Unlike `01`–`05`, this cast uses **no** `synth` data for the install itself. It is an unedited
recording of `pip install token-finops-cli` against the live PyPI index — proof that the published
package installs and that the `token-finops` entry point lands on `$PATH`. The install happens
inside a throwaway virtualenv so the recording host's real environment is never touched, but venv
setup itself isn't part of the visible recording (it starts right at `pip install`) and the venv's
real path is sanitized to a literal `~` (tilde), as if it were a real user's home directory, rather
than leaking a real machine's path or username.

The closing `token-finops adapters` step *is* run against a `synth` home, so the recording never
shows the recording host's real tool inventory; its root paths sanitize to `~/...` the same way.

As of the 2026-09 re-recording, PyPI serves **0.3.0** — the real 9-adapter CLI — so the cast now
ends on `adapters` rather than the `sessions --help` fallback the old 0.2.0-era recording needed.
Note that `doctor` and `savings --co2` landed on `main` *after* the 0.3.0 upload and are therefore
not in the published wheel yet; casts `07` and `08` are recorded against a source checkout.

**Python version matters here:** 0.3.0 requires Python >= 3.10, so a venv built on an older
interpreter silently resolves to 0.2.0 instead. Pin the interpreter explicitly when re-recording.

Re-record it with (`./tmp/` is repo-local and gitignored — see `AGENTS.md`'s "no system `/tmp`"
rule — used so scratch state from recording never leaks outside the repo, and never touches the
real system `/tmp`):

```bash
mkdir -p tmp && rm -rf tmp/token-finops-venv tmp/casthome
uv venv --python 3.12 --seed tmp/token-finops-venv              # >= 3.10, and seed pip into it
uv run token-finops synth --out tmp/casthome --scenario burst   # so `adapters` has fake data to find
cat > tmp/tf-demo.sh <<'SH'
source tmp/token-finops-venv/bin/activate
P=$'\033[1;32m$ \033[0m'
run() { printf '%s%s\n' "$P" "$1"; eval "$1"; echo; sleep 1.2; }
run 'pip install token-finops-cli'
run 'pip show token-finops-cli'
run 'which token-finops'
run 'token-finops adapters'
SH
HOME="$(pwd)/tmp/casthome" PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 TERM=linux \
  asciinema rec docs/casts/06-install-pip.cast --overwrite --headless \
    --window-size 110x40 --output-format asciicast-v2 -i 2 \
    -t 'token-finops: 06-install-pip' -c 'bash tmp/tf-demo.sh'
rm -rf tmp/token-finops-venv tmp/casthome tmp/tf-demo.sh
# sanitize the throwaway venv's and the synth home's real absolute paths
python3 -c "
import os
path = 'docs/casts/06-install-pip.cast'
content = open(path, encoding='utf-8').read()
cwd = os.getcwd()
content = content.replace(cwd + '/tmp/token-finops-venv', '~/token-finops-venv')
content = content.replace(cwd + '/tmp/casthome', '~')
open(path, 'w', encoding='utf-8').write(content)
"
```

## `07-doctor.cast` and `08-savings-co2.cast`

Both run the CLI from a source checkout (`.venv/bin` on `PATH`), because both features postdate the
0.3.0 wheel on PyPI. `07` uses a *partial* synth home — only `copilot` and `claude_code` — precisely
so the output shows both the `[found]` and the `[missing]` tiers with their hints; a full synth home
would print nine `[found]` rows and demonstrate nothing. `08` needs no home at all: `savings` is
pure arithmetic over the packaged JSON.

`doctor` prints the interpreter path in its header, so that gets sanitized too — to the path a real
`uv tool install` would produce rather than to a bare `~`, since a plausible path is more use to a
reader than an obviously-redacted one.

```bash
mkdir -p tmp && rm -rf tmp/dochome
uv run token-finops synth --out tmp/dochome --tools copilot,claude_code --scenario burst
cat > tmp/doc-demo.sh <<'SH'
P=$'\033[1;32m$ \033[0m'
run() { printf '%s%s\n' "$P" "$1"; eval "$1"; echo; sleep 1.5; }
run 'token-finops doctor'
SH
HOME="$(pwd)/tmp/dochome" PATH="$(pwd)/.venv/bin:$PATH" TERM=linux \
  asciinema rec docs/casts/07-doctor.cast --overwrite --headless \
    --window-size 110x80 --output-format asciicast-v2 -i 2 \
    -t 'token-finops: 07-doctor' -c 'bash tmp/doc-demo.sh'
python3 -c "
import os
p = 'docs/casts/07-doctor.cast'; c = open(p, encoding='utf-8').read()
cwd = os.getcwd()
c = c.replace(cwd + '/.venv/bin/python3', '~/.local/share/uv/tools/token-finops-cli/bin/python3')
c = c.replace(cwd + '/tmp/dochome', '~')
open(p, 'w', encoding='utf-8').write(c)
"
rm -rf tmp/dochome tmp/doc-demo.sh
```

`08` is the same shape with `--window-size 110x54` and these two commands:

```bash
run 'token-finops savings --co2 --cloud-region us-virginia'
run 'token-finops savings --co2 --power solar-de-feed-in --cloud-region us-ercot | tail -n 8'
```

After any recording, grep the committed `.cast` for your username and for absolute paths before
committing it — the sanitize step is easy to get half-right.

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
