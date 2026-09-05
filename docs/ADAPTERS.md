# Writing an adapter

An adapter turns one tool's local telemetry into `UsageEvent`s (and, when the
tool writes it to disk, a `QuotaSnapshot`). Rules:

1. **Read-only, always.** SQLite via `adapters.base.sqlite_readonly()` (`immutable=1`),
   files opened for reading only. Never create, lock or repair the tool's data.
2. **stdlib only.** `sqlite3`, `json`, `glob`, `os`, `datetime`, `re`, `urllib` are fine.
3. **Dedup where the source duplicates.** Document the composite key in the module docstring.
4. **Tolerate schema drift.** Use alias lists for field names (`tokens.input | input_tokens | prompt_tokens`),
   skip rows you cannot parse, never raise on one bad line.
5. **Timestamps → aware UTC** (`datetime` with `tzinfo=timezone.utc`).
6. **Fill `usd_estimate`** with `core.pricing.estimate_usd(model, in, out, cache_read, cache_write)`;
   leave `None` for local models and set `is_local_model=True`.
7. **`native_cost` / `native_unit`** only when the tool bills in its own unit (Copilot AIU, Hermes/OpenRouter USD).
8. **`default_policy()`** describes the tool's real budget window (see table in README). If the tool has no
   intrinsic budget, use `Unit.USD` + `CycleKind.NONE`, `allowance=None`.
9. **Tests**: a synthetic fixture builder in the adapter module (`build_synthetic_*`) plus a test in
   `tests/test_<tool>.py` that asserts event count, dedup, model normalisation, and USD > 0.

## Skeleton

```python
from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Iterable, Optional
from ..core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Unit, UsageEvent
from ..core.pricing import estimate_usd, is_local_model
from .base import BaseAdapter, register, sqlite_readonly

@register
class FooAdapter(BaseAdapter):
    tool = "foo"
    display_name = "Foo CLI"

    def default_root(self) -> str:
        return os.environ.get("FOO_HOME", "~/.foo")

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        ...

    def quota(self) -> Optional[QuotaSnapshot]:
        return None

    def default_policy(self, allowance=None) -> BudgetPolicy:
        ...
```

## Field tables (verified 2026-09-04)

### Codex CLI — `${CODEX_HOME:-~/.codex}/sessions/YYYY/MM/DD/rollout-*.jsonl` (+ `archived_sessions/`)
- `type == "session_meta"` → `payload.id`, `payload.cwd`; `type == "turn_context"` → `payload.model`
- `type == "event_msg"` and `payload.type == "token_count"`:
  `payload.info.total_token_usage{input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens, total_tokens}`
  (cumulative per session — emit **deltas**; duplicate rows with unchanged totals exist, skip them; fall back to `last_token_usage`),
  `payload.info.model_context_window`,
  `payload.rate_limits{primary{used_percent, window_minutes≈300, resets_at}, secondary{used_percent, window_minutes≈10080, resets_at}, credits{...}, plan_type}` → **QuotaSnapshot for "5h" and "7d"** from the newest rollout.
- `input_tokens` includes `cached_input_tokens` → cache_read = cached, input = input - cached.
- `reasoning_output_tokens` ⊂ `output_tokens` (`reasoning_is_subset_of_output=True`).
- Policy: `Unit.PERCENT`, `CycleKind.ROLLING`, 5h window, `source_of_truth="provider_pct"`.

### Gemini CLI — `${GEMINI_CLI_HOME:-~/.gemini}/tmp/<projectHash>/chats/session-*.jsonl` (sub-agents in `chats/<parent>/<id>.jsonl`), legacy `*.json`
- First JSONL line: metadata `{sessionId, projectHash, startTime, ...}`.
- Message lines with `type == "gemini"`: `id, timestamp, model, tokens{input, output, cached, thoughts, tool, total}`.
  `input` **includes** `cached` → cache_read = cached, input = input - cached; `thoughts` → reasoning (not subset of output; add to output for pricing? No: Gemini bills thoughts as output → treat `thoughts` as output tokens for USD, keep `reasoning_tokens=thoughts`, `reasoning_is_subset_of_output=False`).
- Project path map: `~/.gemini/projects.json` `{"projects": {"<abs path>": "<slug>"}}`.
- Budget: **requests per day** (free 1000, Standard 1500, Enterprise 2000). Policy: `Unit.REQUESTS`, `CycleKind.DAILY`, `allowance=1000` default.
- Optional quota (not required now): `POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota` with OAuth from `~/.gemini/oauth_creds.json` — reverse-engineered, leave a documented TODO.

### Hermes Agent — `${HERMES_HOME:-~/.hermes}/state.db` (SQLite, WAL)
- Table `sessions`: `id, source, model, started_at, ended_at, message_count, api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, billing_provider, billing_base_url, billing_mode, estimated_cost_usd, actual_cost_usd, cost_status, cost_source, parent_session_id, title`.
- Newer builds: table `session_model_usage` (session × model × billing_provider with the same token/cost columns) — check `sqlite_master`, prefer it, fall back to `sessions`.
- One event per row (session-level granularity is fine; `ts_utc = ended_at or started_at`; epoch seconds or ISO).
- `billing_mode in ("unknown",)` or base_url host in (localhost, 127.0.0.1) or provider in (ollama, lmstudio, vllm, local) → `is_local_model=True`, `usd_estimate=None`.
- `billing_provider == "openrouter"` → `native_cost = actual_cost_usd or estimated_cost_usd`, `native_unit=Unit.USD`.
- Legacy JSONL: `~/.hermes/sessions/<id>.jsonl` — optional.
- Policy: `Unit.USD`, `CycleKind.SLIDING_FROM_FIRST_USE` 30d, `allowance=None` (BYO provider) — `source_of_truth="local_sum"`.
