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

## Commit messages

Imperative subject line, body explains *why* rather than *what*. When a
coding agent authored the change, keep the attribution trailers it adds
(e.g. `Co-Authored-By:`, `Claude-Session:`) — do not strip them.

## Pull request checklist

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
