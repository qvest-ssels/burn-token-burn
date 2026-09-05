# ADR-0012: Ollama and local models

- **Status:** Accepted (2026-09-05, reference-only as proposed)
- **Date:** 2026-09-05

## Context

Ollama **persists nothing** about past requests — no local database, log
file, or history. Its API responses include token counts inline
(`prompt_eval_count`/`eval_count`, or an OpenAI-compatible `usage` object)
but only transiently, in a live response, never recorded to disk. The
same holds for other locally-hosted-model runtimes (LM Studio, vLLM): they
serve tokens but keep no books.

There is no budget concept for a local model — no plan, quota, reset
cycle, or vendor to bill. What matters is throughput and energy cost
against a developer's own hardware, feeding the local-vs-cloud savings
estimator (`savings/local_estimator.py`): "would this workload have been
cheaper locally?"

The only ways to observe local-model usage are indirect: reading it back
out of a *client's* own log when that client routes through a local model
— Hermes Agent (ADR-0005), OpenCode/Kilo (ADR-0006), Cline/Roo (ADR-0007)
— or standing up a logging reverse-proxy in front of Ollama's `:11434`.

## Decision

**No budget; energy/throughput only, captured via client logs or a
logging proxy — feeds the savings estimator, not the runway engine.**
This is not a standalone adapter with its own `scan()`/`quota()` pair
reading a canonical Ollama-owned source (none exists); local-model usage
is folded in wherever another adapter already observes it (Hermes,
OpenCode, Cline/Roo), tagged `is_local_model=True`, `usd_estimate=None`.
As an optional secondary path, document (don't require) a small
logging-proxy pattern in front of `:11434` for client-independent
visibility. `default_policy()`: `Unit.USD`, `CycleKind.NONE`,
`allowance=None` → effectively `UNLIMITED`, with the real signal
(tokens/sec, watts, $/MTok) surfaced via the savings estimator instead.

## Consequences

**What we get:** local-model usage is neither silently dropped nor
falsely assigned a fictitious dollar budget; it flows into the one place
it's actually useful — the break-even/savings calculation comparing local
hardware cost against equivalent cloud spend.

**Risks:**
- Coverage depends entirely on which client was used; a local model
  invoked outside an adapted tool (or via direct `curl`/scripts) is
  invisible.
- A logging proxy, if adopted, adds an operational component out of
  character for this project's read-local-files-only model, and could
  raise privacy concerns if misconfigured to listen beyond localhost.
- Throughput/power numbers used by the savings estimator are largely
  aggregator-sourced rather than measured; the estimator ships editable
  JSON defaults and documents `powermetrics`/`nvidia-smi`/`llama-bench`
  for measuring one's own hardware instead of trusting defaults blindly.

## Alternatives considered

- A standalone Ollama-only adapter polling its API live was rejected: it
  would duplicate what Hermes/OpenCode/Cline already do incidentally, and
  still miss calls outside its observation window.
- A dedicated Ollama logging proxy is a documented option in this
  project's research, but not a currently-shipping open-source tool to
  point to; it stays a "build it yourself" note, not a recommendation.

## Open questions

- Is a minimal, optional logging-proxy script worth shipping in this
  repo (not as a daemon, but as an opt-in wrapper), given no existing
  tool fills this gap?
- Should local-model coverage via Hermes/OpenCode/Cline be documented as
  "best-effort, client-dependent" directly in the CLI's help output, not
  just in the docs?
