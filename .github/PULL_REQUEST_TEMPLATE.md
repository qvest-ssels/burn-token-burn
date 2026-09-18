<!--
Rules: AGENTS.md. PR mechanics: CONTRIBUTING.md. Delete whatever doesn't apply —
this is a prompt, not a form to be filled in dutifully.
-->

## What and why

<!-- Imperative summary, then the reason. The diff already says what changed. -->

Closes #

## Checklist

- [ ] `uv run pytest -q` passes.
- [ ] `uv run ruff check .` passes.
- [ ] Assistant support added or changed → its ADR in `docs/adr/` is updated
      (status, tier, open questions) in this same PR.
- [ ] A price, quota, endpoint, hardware or energy figure changed →
      `docs/sources.md` (or the relevant `savings/*.json` entry) cites the source
      and a review date. Uncited numbers are labelled as estimates.
- [ ] No real telemetry, `__pycache__` or `.venv` content committed — fixtures
      come from `token-finops synth`.

## Agentic work only

<!-- Skip this section if a human wrote the change. -->

- [ ] `AGENTIC.md` has a row for this branch, flipped to `PR opened`.
- [ ] `claude-tasks.md` box ticked, if this closes a T-NN task.

<details>
<summary><code>uv run token-finops self-audit</code> — by-model table</summary>

```
paste here
```

</details>
