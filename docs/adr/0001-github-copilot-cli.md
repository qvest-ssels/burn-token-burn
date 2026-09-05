# ADR-0001: GitHub Copilot CLI adapter

- **Status:** Proposed
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

## Open questions

- Should we adopt the RE `copilot_internal/user` endpoint as an optional
  `--online` cross-check, given it is unversioned but self-used by the
  official CLI?
- How does an Enterprise contract with a non-standard cycle day interact
  with the hardcoded 1st-of-month reset — expose `--cycle-day` as in the
  original?
