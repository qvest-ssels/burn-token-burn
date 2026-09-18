# Contributing

Read [`AGENTS.md`](AGENTS.md) first — it is the single set of rules for
coding agents (and humans) working in this repository: read-only against
tool data, standard library only, one ADR per assistant, fractions not
dollars. This file adds the PR mechanics; [`DEVELOPING.md`](DEVELOPING.md)
is the broader day-to-day workflow hub (test subsets, synthetic telemetry,
debugging an adapter, releasing).

## Setup

```bash
uv venv
uv pip install -e "token-finops-cli[dev]"
source .venv/bin/activate   # or prefix every command below with `uv run`
```

## Run tests and lint

```bash
uv run pytest -q            # from token-finops-cli/, or repo root — pytest picks up token-finops-cli/tests
uv run ruff check .          # line length 110, see token-finops-cli/pyproject.toml
```

CI (`.github/workflows/ci.yml`) runs both on Python 3.10–3.13. Keep it green.

## Adding a new assistant/adapter

1. Read or write its ADR first: `docs/adr/00NN-<assistant>.md` (copy an
   existing one as a template, status *Proposed*). The ADR records where
   the tool stores telemetry, what budget unit (if any) the provider
   enforces, whether remaining quota is knowable offline, and whether the
   data source is official or reverse-engineered — see
   [`docs/adr/README.md`](docs/adr/README.md) for the tiering rule.
2. Implement `token-finops-cli/src/token_finops_cli/adapters/<tool>.py`
   following the conventions in [`docs/ADAPTERS.md`](docs/ADAPTERS.md):
   `scan()`, optional `quota()`, `default_policy()`, and
   `build_synthetic_<tool>()` so `token-finops synth` can generate fixtures
   for it.
3. Register the adapter in `adapters/__init__.py::all_adapters()`.
4. Add `tests/test_<tool>.py` against the synthetic fixture: event count,
   dedup behaviour, model normalisation, USD estimate present (or `None`
   for unbilled/local models), and the policy's unit.
5. Update the ADR status to *Accepted* and the support table in the root
   `README.md`.
6. If you need example data for a bug report or a demo instead of a unit
   test, use `token-finops synth --out DIR --tools <tool>` rather than
   committing real telemetry — see [`docs/SYNTH.md`](docs/SYNTH.md) for
   the available scenarios (`steady`, `burst`, `exhausted`, `weekend`,
   `fresh`, `quiet`, `subagent-heavy`).

## Filing an issue

The issue chooser has five forms, and which one you pick matters more than
usual here:

- **Parser / adapter drift** — an assistant changed its on-disk format and
  the adapter stopped reading it. Expected, not exceptional (`AGENTS.md`
  rule 7). Needs the assistant's version and a *sanitized* sample of the
  new shape — never real telemetry; `token-finops synth` exists for this.
- **Bug report** — anything else broken.
- **Support a new assistant** — asks the ADR question set (where telemetry
  lives, what budget unit the provider enforces, whether quota is knowable
  offline, official vs. reverse-engineered), so a filled form is most of a
  *Proposed* ADR instead of a wish.
- **Feature request** — optionally shaped as a `claude-tasks.md` entry
  (size + acceptance criteria), which makes it pickup-ready for whoever —
  or whatever — takes it.
- **Wrong or stale number** — a price, quota, hardware or energy figure
  that needs re-sourcing. Primary source and review date required, same
  rule the repo holds itself to.

Anything that isn't one of those: open a blank issue and write it down.
There are no Discussions on this repo, so issues are the one inbox. Triage
is one maintainer and the occasional coding agent — the built-in labels
(`bug`, `enhancement`, `documentation`, `question`, `help wanted`) are all
the process there is.

## Commit messages

Imperative subject line, body explains *why* rather than *what*. When a
coding agent authored the change, keep the attribution trailers it adds
(e.g. `Co-Authored-By:`, `Claude-Session:`) — do not strip them.

## Pull request checklist

`.github/PULL_REQUEST_TEMPLATE.md` pre-fills this list into every PR, so
you shouldn't have to copy it by hand:

- [ ] `uv run pytest -q` passes.
- [ ] `uv run ruff check .` passes.
- [ ] If you added or changed an assistant's support: its ADR in
      `docs/adr/` is updated (status, tier, open questions) in the same PR.
- [ ] If you changed a price, quota, endpoint or hardware/energy figure:
      `docs/sources.md` (or the relevant `savings/*.json` entry) cites the
      source and review date.
- [ ] `uv run token-finops self-audit` was run at the end of the session
      and its by-model table is pasted into the PR description — this repo
      eats its own dog food (see `AGENTS.md` rule 8).
- [ ] No real telemetry, `__pycache__`, or `.venv` content is committed —
      use `token-finops synth` for fixtures.

## Code of conduct

Be respectful and assume good faith; disagreements are about the code and
the data, not the person.
