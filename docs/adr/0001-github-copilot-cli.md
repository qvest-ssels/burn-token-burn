# ADR-0001: GitHub Copilot CLI adapter

- **Status:** Accepted (2026-09-05, adapter implemented)
- **Date:** 2026-09-05

## Context

GitHub Copilot CLI is the origin of this project: `token-finops-cli` (Stefan's
stdlib-only tool) already reads it read-only from `~/.copilot/session-store.db`,
table `assistant_usage_events`. The real schema also carries `model`,
`cache_read_tokens`, `cache_write_tokens`, `agent_id`, `parent_tool_call_id`,
`initiator`, and `request_multiplier`, which lets sub-agent calls be
attributed rather than folded into one total. An alternative, less-used
source exists in `session-state/<uuid>/events.jsonl` (`assistant.usage`
records).

The budget unit is **AI-credits/units**: `total_nano_aiu / 1e9` yields
credits, and 1 credit = $0.01. The cycle is a **calendar month, resetting
00:00 UTC on the 1st** — a fixed, documented reset rule, not a rolling
window. Plan allowances are published: Pro 1,500, Pro+ 7,000, Max 20,000,
Business 1,900, Enterprise 3,900 (including Flex credits).

Remaining quota is available **offline**, computed directly from the local
event sum against the plan allowance — no network call is required to know
"how much is left". An optional, reverse-engineered online source exists as
well: `GET api.github.com/copilot_internal/user`, which returns
`quota_snapshots.chat.percent_remaining` and `quota_reset_at`; the Copilot
CLI itself uses this endpoint, and GitHub's own SDK exposes it as
`account.getQuota`, so it is unofficial-but-corroborated rather than purely
speculative. Known pitfall: compaction consumes tokens without writing an
event row, and this can bias burn-rate calculation slightly.

## Decision

**Full adapter.** Read `assistant_usage_events` (or the JSONL fallback),
sum `total_nano_aiu` since cycle start, and compute a runway against the
plan's monthly credit allowance, exactly as `token-finops-cli` does today.
This is a straightforward port with fixes: open the DB with `immutable=1`,
read the newly-verified optional columns for model/cache/agent
attribution, and fix the cycle boundary to 1st-of-month 00:00 UTC.

## Consequences

**What we get:** the reference implementation for every other adapter —
local-only, no auth, no RE endpoint required for the core runway feature,
and sub-agent-level attribution once the optional columns are read.

**Robustness:** The adapter tolerates missing columns (e.g. when the `model`,
`cache_read_tokens`, or `cache_write_tokens` columns are absent from the
database) and falls back to sensible defaults; it also handles rows with
TEXT values in numeric columns and unparsable timestamps by skipping only
the affected rows. Corrupt SQLite files are skipped silently rather than
raising an error.

**Risks:**
- Schema drift: the optional columns are undocumented; if GitHub renames or
  drops them, we degrade gracefully to total-only accounting (already the
  `adapters.base` convention: alias lists, skip unparsable rows).
- Compaction tokens are invisible to this table, causing a small
  underestimate of true consumption near context-window limits.
- The RE endpoint (`copilot_internal/user`), if we ever adopt it for a
  live percent-remaining cross-check, is unversioned and could break
  without notice.

## Alternatives considered

- **ccusage** (Copilot is one of 14+ sources it supports) — mature, but a
  Rust/Node tool; we port the concept, not the code, to keep this project
  stdlib-only Python.
- **token-finops-cli** itself — this *is* the source we are porting; we
  keep it as the canonical upstream reference in `docs/landscape.md`.

## Online cross-check (T-03, 2026-09-22)

The open question below is now answered: **yes, as an opt-in flag.**
`token-finops report|status --online` calls `GET
api.github.com/copilot_internal/user` with a token read (never written)
from `$GITHUB_TOKEN`/`$GH_TOKEN` or `gh auth token`, and turns
`quota_snapshots.chat.percent_remaining` into a `QuotaSnapshot` with
`source="copilot_online"` (distinct from the offline local sum) plus
`quota_reset_date` as the reset. On success that run's
`source_of_truth` is promoted `local_sum` -> `hybrid`: GitHub's own
percentage decides "how much is left", local events still drive the burn
rate. Implementation: `token_finops_cli/online.py` (stdlib `urllib`).

The endpoint stays unversioned and self-used-by-the-CLI rather than
documented, so the adoption is hedged three ways: it never fires without
the explicit flag, the response is cached >= 180 s in
`~/.token-finops/online-cache.json`, and every failure (no token, no
network, non-2xx, non-JSON, drifted shape) falls back silently to the
offline path — a `--online` run on a disconnected machine prints
byte-identical output to a run without the flag. Copilot is the one tool
here where the offline runway is already authoritative, so this is a
cross-check, not a dependency.

## Open questions

- ~~Should we adopt the RE `copilot_internal/user` endpoint as an optional
  `--online` cross-check, given it is unversioned but self-used by the
  official CLI?~~ Answered by T-03 (see above): yes, opt-in and fail-closed.
- Should a large divergence between the online percentage and the local sum
  be surfaced as a note (it would be evidence for the compaction-token
  undercount above) rather than silently replacing the local number?
- How does an Enterprise contract with a non-standard cycle day interact
  with the hardcoded 1st-of-month reset — expose `--cycle-day` as in the
  original?
