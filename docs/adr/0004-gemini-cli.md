# ADR-0004: Gemini CLI adapter

- **Status:** Accepted (2026-09-05, adapter implemented)
- **Date:** 2026-09-05

## Context

Gemini CLI writes per-session JSONL to
`${GEMINI_CLI_HOME:-~/.gemini}/tmp/<projectHash>/chats/session-*.jsonl`,
with sub-agent transcripts in `chats/<parent>/<id>.jsonl`; a legacy
`*.json` format also exists. The first line of each file is session
metadata (`sessionId`, `projectHash`, `startTime`, ...). Message lines with
`type == "gemini"` carry `id, timestamp, model,
tokens{input, output, cached, thoughts, tool, total}`. `input` already
**includes** `cached` (subtract to get true input / cache-read), and
`thoughts` (reasoning) is billed by Google **as output**, unlike OpenAI —
so, unusually among these adapters, `reasoning_is_subset_of_output=False`
and `thoughts` must be added into the output-token count used for USD
estimation while still being reported separately as `reasoning_tokens`.
Project-path resolution uses `~/.gemini/projects.json`
(`{"projects": {"<abs path>": "<slug>"}}`).

The budget unit is **requests per day**, not tokens or dollars: Free tier
1,000/day, Standard 1,500/day, Enterprise 2,000/day (Pro/Ultra tiers'
limits are unpublished). The reset is daily, but the **reset timezone is
undocumented** — a known pitfall, alongside Copilot's UTC cycle being the
one clearly documented one. Remaining quota is not written to local
transcripts at all; there is an optional reverse-engineered call, `POST
cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota`, returning
`buckets[{remainingFraction, resetTime}]`, but it requires OAuth
credentials from `~/.gemini/oauth_creds.json` and is undocumented/RE only.

## Decision

**Full adapter.** Count local JSONL sessions (main + sub-agent files) as
`UsageEvent`s with token detail for cost/attribution purposes, and build
the runway against the **locally-countable requests/day** budget: sum
requests since local-day start and compare to the plan's default allowance
(1,000/day as the conservative default, user-overridable). This gives a
real, offline runway on the unit Google actually enforces (requests), even
though the exact reset-timezone boundary is a documented approximation.
The RE `retrieveUserQuota` endpoint is left as an optional, clearly-labeled
TODO rather than a dependency, per the project's own research notes.

## Consequences

**What we get:** an offline requests/day runway plus rich per-token
attribution for cost reporting, without any network dependency for the
core feature.

**Robustness:** The adapter handles garbage appended to JSONL files (truncated
JSON, whitespace-only lines, valid-but-wrong-shape JSON objects), keeps all
intact message events when a file's tail is truncated, normalizes multiple
timestamp formats (ISO 8601, epoch milliseconds, and future-dated values) to
UTC, and gracefully processes unknown model IDs and extra/unexpected fields.
Malformed files are skipped without raising.

**Risks:**
- Reset timezone is undocumented; our locally-computed "day boundary" may
  disagree with Google's actual reset instant near midnight, causing a
  transient over- or under-count right at the boundary.
- Pro/Ultra allowances are unpublished — our defaults may be wrong for
  those plans until a user supplies `--allowance`.
- `thoughts`-as-output billing is easy to get backwards if this adapter's
  logic is ever copied into another provider's adapter by analogy — must
  stay documented inline.
- The RE quota endpoint, if adopted, needs OAuth token handling and could
  break silently on Google's side.

## Alternatives considered

- **cc-statistics**, **tokscale** — multi-tool dashboards that already
  parse this JSONL shape; useful field-alias references.
- **agy-quota** — specifically targets the internal quota endpoint for
  Gemini/Antigravity; a candidate to study before implementing the
  optional online path.
- **gemini-cost-tracker**, **geminiusage** — narrower single-tool trackers,
  listed in `docs/landscape.md`.

## Open questions

- What timezone does Google actually use for the daily reset, and can it
  be inferred empirically from `retrieveUserQuota.resetTime` samples?
- Should Pro/Ultra allowances be crowd-sourced/configurable given they are
  unpublished?
