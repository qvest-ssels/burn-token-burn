# Homebrew formula for `token-finops-cli`

`token-finops-cli` is a small, stdlib-only Python CLI (see `dependencies = []`
in `token-finops-cli/pyproject.toml`) already published on PyPI:
https://pypi.org/project/token-finops-cli/

`token-finops-cli.rb` in this directory is a standard
`Language::Python::Virtualenv`-based Homebrew formula for it. Since the
package has no third-party PyPI dependencies, it needs no `resource` blocks —
just the sdist `url`/`sha256` and a `virtualenv_install_with_resources` install
step.

## Test it locally right now (throwaway local tap)

Modern Homebrew rejects path-based `install`/`audit` ("Calling `brew audit
[path ...]` is disabled! Use `brew audit [name ...]` instead.") -- a formula
must live in a tap and be referenced by name, even a throwaway local one:

```sh
brew tap-new local/tfops --no-git
cp contrib/homebrew/token-finops-cli.rb "$(brew --repo local/tfops)/Formula/token-finops-cli.rb"

brew audit --strict --formula local/tfops/token-finops-cli
brew style local/tfops/token-finops-cli
brew install --build-from-source local/tfops/token-finops-cli
token-finops --help

brew uninstall token-finops-cli   # clean up when done
brew untap local/tfops
```

This exact sequence runs on every push/PR that touches the formula via
`.github/workflows/homebrew-smoke.yml`.

## Distributing it as `brew install token-finops-cli`

To let users run a plain `brew install token-finops-cli` (or
`brew tap ... && brew install ...`) without pointing at this file, there are
two options — both are decisions for a human maintainer to make later, not
something this repo does automatically:

1. **Submit to homebrew-core.** This is the path that gives users a bare
   `brew install token-finops-cli` with no tap step. homebrew-core has
   notability/popularity requirements (a track record of real-world usage,
   GitHub stars, etc. — see
   [Homebrew's acceptable formulae criteria](https://docs.brew.sh/Acceptable-Formulae))
   that this project likely does not yet meet.
2. **Maintain a custom tap.** Create a separate repo named
   `homebrew-<name>` (e.g. `qvest-ssels/homebrew-token-finops`) containing a
   `Formula/token-finops-cli.rb` (this file, or a near-copy of it). Users
   would then run:

   ```sh
   brew tap qvest-ssels/token-finops
   brew install token-finops-cli
   ```

   This has no popularity bar and can be set up immediately, but it does mean
   maintaining a second repo (and bumping `url`/`sha256` on every release).

No such tap repo has been created as part of this change — that's left for a
human to decide on.
