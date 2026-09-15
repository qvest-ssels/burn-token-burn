# ADR-0013: Claude Desktop & Cowork (macOS)

- **Status:** Proposed (2026-09-14) — split verdict, see *Decision*
- **Date:** 2026-09-14
- **Investigated on:** macOS 25.5.0 (arm64), Claude Desktop with Cowork enabled,
  bundled Claude Code 2.1.260

## Context

The question from the field was "can we measure Claude Desktop?". Three different
products share one macOS app bundle and one account, and they turn out to leave
three *very* different amounts of evidence on disk. Everything below was verified
by reading `~/Library/Application Support/Claude/` on a real machine — read-only,
nothing written, nothing deleted (`AGENTS.md` rule 1 and the home-directory rule).

The working assumption going in was "desktop chat keeps no local telemetry, so the
only account-wide number is the OAuth usage percentage from `--online` (T-03)".
That assumption held for the chat app and was **wrong in two useful directions**:
Desktop caches the account-wide quota percentages *offline*, and on-computer Cowork
mirrors full Claude-Code-grade usage records outside the VM.

### What is actually in `~/Library/Application Support/Claude/`

It is an Electron/Chromium profile plus app state — 58 entries. The bulk of it is
browser plumbing with no usage meaning: `Cache` (~1.1 GB), `Code Cache`, `GPUCache`,
`DawnGraphiteCache`, `DawnWebGPUCache`, `Cookies`, `Network Persistent State`,
`TransportSecurity`, `Trust Tokens`, `DIPS`, `InterestGroups`, `Session Storage`,
`Shared Dictionary`, `shared_proto_db`, `VideoDecodeStats`, `Crashpad`, `sentry`.

App state worth naming:

| Path (under `~/Library/Application Support/Claude/`) | What it is | Usage-shaped? |
|---|---|---|
| `plan-usage-history.json` | **Local time series of account-wide quota utilisation.** See below. | **Yes** |
| `local-agent-mode-sessions/<accountId>/<orgId>/local_*/audit.jsonl` | **On-computer Cowork transcripts + token accounting.** See below. | **Yes** |
| `claude-code-sessions/<accountId>/<orgId>/local_*.json` | Cloud Cowork session *metadata* only | No |
| `config.json` | App prefs, `oauth:tokenCache` / `oauth:tokenCacheV2`, `lastKnownAccountUuid`, extension allowlist caches | No (credentials, not usage) |
| `claude_desktop_config.json` | MCP server configuration | No |
| `IndexedDB/https_claude.ai_0.indexeddb.leveldb` | The claude.ai webview's own cache (~3.6 MB) | Token-shaped but unusable — see below |
| `vm_bundles/claudevm.bundle/` | The on-computer Cowork VM: `rootfs.img` and `sessiondata.img`, 10 GB each, plus `vmlinuz`, `initrd`, `efivars.fd` | No (and not needed) |
| `claude-code/2.1.260/`, `claude-code-vm/2.1.260/` | Bundled Claude Code binaries for host and VM | No |
| `git-shadow/`, `git-worktrees.json`, `pending-uploads/`, `spaces-present/`, `Claude Extensions*/`, `buddy-tokens.json`, `ant-did`, `ant-device-registry.json`, `vm-support-probe.json`, `cowork-enabled-cli-ops.json`, `window-state.json`, `fcache`, `ca-bundle.pem`, `extensions-*.json`, `Preferences`, `Local State`, `declarative_performance_observer.db` | Device identity, extensions, VM capability probe, window geometry | No |

A `grep -rl "input_tokens" --include="*.json"` across the whole directory returns
**zero** hits outside the Cowork session tree. There is no per-message token
accounting for the desktop **chat** app anywhere on disk.

### 1. Claude Desktop (the chat app) — no local usage telemetry

Conversations are server-side, as expected. The only local trace of chat content is
inside `IndexedDB/https_claude.ai_0.indexeddb.leveldb`, which is the claude.ai web
app's own cache running inside the Electron webview. Dumping strings from its
`.ldb`/`.log` files does show token-shaped keys — `conversationUuid`,
`messageCount`, `canonicalModel`, `cache_creation`, `ephemeral_1h_input_tokens` —
alongside raw prompt and response text.

This is **not** a parse target for this project:

- It is a LevelDB written by a process that is usually running; there is no
  `immutable=1` equivalent and no safe read-only snapshot path.
- The schema is the web app's internal IndexedDB serialisation (undocumented,
  version-coupled to whatever claude.ai shipped that week) — the opposite of the
  "field-alias lists over a documented format" model in `docs/ADAPTERS.md`.
- It is a *cache*: it holds whatever conversations the app happened to hydrate, not
  a complete or stable record. Any total computed from it would be silently wrong.
- It interleaves full conversation text with the counters, which is a privacy
  liability a budget tracker has no reason to take on.

### 2. `plan-usage-history.json` — the account-wide number, cached offline

This is the find that changes the verdict. Claude Desktop writes a compact,
append-only sample series of the *account-wide* rate-limit utilisation:

```json
{ "version": 2,
  "samples": [ { "t": 1789416148528, "org": "<orgId>", "u": { "fh": 11, "sd": 27 } } ] }
```

Verified on this machine: `version` 2, **241 samples spanning 2026-08-16 →
2026-09-14** (~30 days) at roughly 15-minute cadence, tagged by `org` (two orgs
present on this account). Fields:

| Field | Meaning | Observed range |
|---|---|---|
| `t` | Unix epoch **milliseconds** | 30 days of history |
| `org` | Organisation UUID the sample belongs to | 2 distinct |
| `u.fh` | **five-hour** window utilisation, percent | 0 – 65 (integer) |
| `u.sd` | **seven-day** window utilisation, percent | 0 – 43 (integer) |
| `u.xu` | extra-usage / overage utilisation, percent — present on only 44 of 241 samples | 7.38 – 100 (float) |

The `fh`/`sd` naming lines up exactly with the `five_hour` / `seven_day`
`unifiedWindows` that Claude Code itself receives (see §3), and the sawtooth in the
data matches window resets (`fh` drops 61 → 2 between consecutive samples).

The significance for this project: T-03 treats the account-wide usage percentage as
an **online-only** number requiring an OAuth call. On any Mac with Claude Desktop
installed, the same number — *and its history* — is already on disk, and history is
strictly better than a point sample because it is what a pace/burn-rate calculation
needs. This is the one number that spans Desktop **+** Code **+** Cowork, since the
rate-limit windows are enforced per account, not per product.

Caveats: it is percentages, never tokens, so it cannot be attributed to a tool or a
model; it is undocumented and the `version: 2` field is an explicit invitation to
schema drift; and it only exists if Claude Desktop is installed and has been run.

### 3. Cowork — cloud sessions vs. on-computer sessions

These are two genuinely different answers and the task's framing only anticipated
the first one.

**Cloud Cowork: metadata only, premise confirmed.**
`claude-code-sessions/<accountId>/<orgId>/local_*.json` (39 files here) are session
*descriptors*: `sessionId`, `cliSessionId`, `cwd`, `createdAt`, `lastActivityAt`,
`model`, `effort`, `title`, `permissionMode`, `enabledMcpTools`,
`remoteMcpServersConfig`, `completedTurns`. There are no transcripts and no token
counts — `grep input_tokens` over the tree is empty, and there are no per-session
subdirectories at all. The transcript lives in the cloud sandbox. So the task's
prescription stands: to measure a cloud Cowork session you must run
`token-finops self-audit` **inside** the session and export the JSON into the repo,
exactly as this repository has been doing.

**On-computer Cowork: transcripts *are* reachable, with full token accounting.**
The task asked whether the local VM's transcripts can be reached. They can — and
not by mounting the 10 GB `sessiondata.img`. They are mirrored onto the Mac's own
filesystem at:

```
~/Library/Application Support/Claude/local-agent-mode-sessions/<accountId>/<orgId>/
    local_<uuid>.json      session descriptor
    local_<uuid>/
        audit.jsonl        the transcript + usage records
        .audit-key         HMAC key
        .claude/  outputs/  uploads/  uploads-tmp/
```

Verified on this machine: **3 687 session directories, every one of them containing
an `audit.jsonl`**, spanning 2026-02-05 → 2026-09-14, ~2.2 GB total. Each line is a
JSON record with `type`, `uuid`, `session_id`, `timestamp`, plus `_audit_timestamp`
and `_audit_hmac` (the records are integrity-signed). Record types seen: `system`,
`user`, `assistant`, `command_lifecycle`, `rate_limit_event`, `result`.

The three that matter:

- `assistant` → `message.usage` — the standard Anthropic usage block:
  `input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`, `cache_creation.{ephemeral_5m,ephemeral_1h}_input_tokens`,
  `service_tier`.
- `result` → `total_cost_usd`, `num_turns`, `duration_ms`, an aggregate `usage`
  (including `output_tokens_details.thinking_tokens`, `server_tool_use`, and a
  per-turn `iterations` array), and **`modelUsage`** keyed by canonical model:
  `inputTokens`, `outputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`,
  `webSearchRequests`, `costUSD`, `contextWindow`, `maxOutputTokens`,
  `thinkingTokens`, `canonicalModel`, `provider`, `costBasis`.
- `rate_limit_event` → `rate_limit_info` with `status`, `rateLimitType`, `resetsAt`,
  `overageStatus`, `isUsingOverage`, and `unifiedWindows.{five_hour,seven_day}`
  each carrying `utilization` (0–1 float) and `resetsAt`.

A spot check over 100 session directories found a `result` record with
`total_cost_usd` in **100 of 100**. This is the same grade of data as
`~/.claude/projects/**.jsonl` — arguably better, because the quota window
utilisation is written to disk next to the tokens instead of having to be scraped
from a status-line hook as ADR-0002 must do.

Note on `sessionType`: 3 658 of the 3 687 descriptors carry
`sessionType: "scheduled"` with `hostLoopMode: true`, the remainder have no
`sessionType`. All of them have an `audit.jsonl` regardless, so an adapter should
not filter on it.

## Decision

A single tier does not describe this product family honestly, so this ADR records
three, one per surface. None of them is implemented by this ADR's PR — this is a
docs-and-investigation change; the adapter work is scoped as follow-up tasks.

1. **Claude Desktop (chat) — reference-only.** No usable local usage telemetry. Do
   not parse the claude.ai webview's IndexedDB. Users asking "what did my Desktop
   chatting cost?" get the account-wide percentage (item 2), not a per-conversation
   number, and that limitation should be stated plainly rather than papered over.

2. **Account-wide quota — usage-via-online, but satisfiable offline on macOS.**
   Treat `plan-usage-history.json` as a *quota* source (a `quota()` implementation,
   not a `scan()`), producing five-hour and seven-day utilisation snapshots with
   real history. It should be preferred over the T-03 `--online` OAuth call when
   present, with `--online` remaining the fallback for machines without Claude
   Desktop. Because it is percentages only, it feeds the binding-constraint roll-up
   but contributes no tokens and no USD — consistent with rule 4.

3. **Cowork — split.**
   - *Cloud sessions:* reference-only on the Mac. Document the in-session
     `self-audit` + JSON-export workflow as the supported route; there is nothing
     on the host to parse.
   - *On-computer sessions:* **full adapter is feasible** and should be proposed as
     its own task. `local-agent-mode-sessions/**/audit.jsonl` carries tokens, USD,
     per-model breakdown *and* window utilisation, which is everything
     `compute_runway` needs. Reuse the Claude Code normalisation path rather than
     writing a parallel one.

The macOS menu-bar surface needs nothing new: `status --format xbar` (SwiftBar)
already renders whatever quota source wins.

## Consequences

**What we get:** an honest answer to "can we measure Claude Desktop?" — *the chat
app, no; your account's quota, yes and offline; your on-computer Cowork work, yes
in full detail*. If item 2 lands, the headline Claude quota number stops requiring
a network call on macOS, which matters for the offline-by-default rule. If item 3
lands, a large and currently invisible chunk of spend (3 687 sessions and ~2.2 GB
of transcripts on this one machine) becomes measurable.

**Risks:**

- **Undocumented formats.** Neither `plan-usage-history.json` nor `audit.jsonl` is
  a published interface. Both must be parsed under rule 7 (field-alias lists, skip
  unparsable records, never raise on one bad line) and both need a synthetic fixture
  builder. The `version: 2` key is a standing warning.
- **Path volatility.** The `<accountId>/<orgId>` nesting means an adapter has to
  glob, not hardcode, and has to decide what to do when several orgs are present —
  the samples are already per-org and must not be summed across orgs.
- **Double counting.** On-computer Cowork runs a bundled Claude Code. If those
  sessions ever also appear under `~/.claude/projects/`, a naive roll-up would count
  them twice; the T-15 `event_id` dedup approach is the model to follow. This needs
  checking before item 3 ships.
- **Privacy.** `audit.jsonl` contains full conversation text, and the descriptors
  carry `emailAddress`, `accountName`, `cwd` and `systemPrompt`. An adapter must
  read counters only and must never copy transcript content into reports, fixtures
  or the repo.
- **Cost of scanning.** 2.2 GB across 3 687 directories is not a cheap `scan()`.
  Item 3 needs incremental/mtime-bounded reading, not a full sweep per invocation.

## Alternatives considered

- **Mount `sessiondata.img` / `rootfs.img`.** Rejected, and unnecessary: the
  transcripts are already mirrored outside the VM. Attaching a 10 GB disk image
  belonging to a possibly-running VM would also violate the read-only posture in
  spirit as well as risk corruption.
- **Parse the claude.ai IndexedDB for Desktop chat usage.** Rejected — see §1.
  `claude-usage-tracker` ([658jjh](https://github.com/658jjh/claude-usage-tracker))
  advertises Claude Desktop coverage with heuristic paths; that is the reference to
  point at, with the caveat attached.
- **Online-only quota via the OAuth endpoint (status quo, T-03).** Kept as the
  cross-platform fallback, demoted to second choice on macOS where
  `plan-usage-history.json` exists and carries history the endpoint does not.
- **Treating Desktop + Code + Cowork as one "Claude" row.** Rejected: they have
  different data availability and the support table's job is to tell the truth about
  each. They *do* share one quota, which is precisely why item 2 is account-wide.

## Open questions

- Do on-computer Cowork sessions also write to `~/.claude/projects/`? Must be
  answered before item 3 ships, or the roll-up double counts.
- Is `u.xu` overage/extra-usage utilisation, and why is it present on only ~18 % of
  samples — is it written only while an overage window is active?
- Is the `plan-usage-history.json` sample cadence fixed (~15 min) or adaptive, and
  is the file trimmed to a 30-day window or simply young on this machine?
- Are the paths identical on Windows and Linux Claude Desktop builds, and is
  `local-agent-mode-sessions` present at all where the VM is unavailable
  (`vm-support-probe.json` reports `virtSupport` per host)?
- Can `_audit_hmac` be verified with `.audit-key`, and is a tamper-evident usage log
  worth anything to a budget tracker, or is it noise for our purposes?
