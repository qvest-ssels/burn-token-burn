# User journeys for the docs site

Status: design/ideation document, 2026-09-14. Written against the in-flight multi-page docs
restructure (sticky top nav: **overview/install → report → status line → self-audit →
savings → synth**, each page embedding asciinema players at ~60% viewport width). Everything
below is grounded in what the CLI does today (`token-finops-cli/README.md`) and what the six
recordings actually show (`docs/casts/README.md`). Backlog items are named as backlog
(`claude-tasks.md`), never presented as shipped.

---

## Persona 1: the first-time user

**Who:** found the repo via an awesome-list, a blog post, or a colleague's tmux screenshot.
Probably runs at least one of Claude Code / Copilot CLI / Codex already. Has never heard the
words "runway" or "binding constraint" in this tool's sense. Gives the site **under 60
seconds** before deciding to bounce or install.

### What they need to understand first (in order)

1. **What it is in one sentence:** it reads the telemetry your coding agents already write to
   disk and tells you how long your budget lasts at your current burn rate.
2. **What it is NOT:** it never phones home, never writes to any tool's data, needs no API
   keys, no accounts, no config. This is the trust gate — a tool that reads `~/.claude` and
   `~/.copilot` sounds invasive until "read-only, offline, stdlib-only" is stated plainly.
3. **The minimum path to one useful command:** install → `token-finops adapters` →
   `token-finops report --compact`. Three commands, zero configuration, real output about
   *their own* usage. That is the whole first-run promise.

### The vocabulary problem

Three terms will confuse a newcomer if used before being defined:

- **"runway"** — time until the budget runs out at the current burn rate. One parenthetical
  on the homepage fixes it: *"runway — how long until you hit the limit, at today's pace"*.
  Do not assume the aviation/startup metaphor lands; the compact report prints `runway 1.9h`
  with no explanation.
- **"binding constraint"** — the tool whose budget runs out first. The compact report's last
  line (`binding constraint: Claude Code (5h) — runway 1.9h -> WARN`) is the single most
  valuable line the tool prints, and also the most jargon-dense. The report page must decode
  it: *"you track several tools with different budget units; they are never summed; this is
  the one that will stop you first."*
- **"self-audit"** — reads as "security audit" to a newcomer. It is actually "what did my
  Claude Code session cost, by model and sub-agent". The nav label should carry a hint (see
  recommendations).

A fourth, quieter trap: **units differ per tool** (Copilot AI units, Claude Code opaque
window %, Gemini requests/day, BYO-key tools in $). The homepage should say "heterogeneous
units are never summed" in plain words once, or the compact report screenshot looks like it
is comparing apples to apples.

### Step-by-step journey (target design)

1. **Lands on the homepage (overview/install).** Sees: one-sentence pitch, the trust bullets
   (read-only / offline / stdlib-only / no keys), the three-command quickstart, and ONE
   teaser recording — `01-report.cast` is the right one (it shows `adapters` then
   `report --compact` then the full report: exactly the first-run experience). The install
   cast (`06`) belongs in the install section further down the same page, not as the hero —
   watching `pip install` scroll by sells nothing.
2. **Scans the install block.** Critical honesty point: PyPI currently serves **0.2.0**
   (Copilot-only); the 9-adapter 0.3.x CLI is install-from-checkout until T-05 ships
   (`docs/INSTALL.md` already says this). The homepage MUST reflect whichever is true at
   publish time. Nothing burns first-timer trust faster than `pip install token-finops-cli`
   followed by `token-finops adapters` not existing.
3. **Runs `token-finops adapters`.** First micro-aha: the table shows which of their agents
   were found, with real paths, no config. The homepage should show this exact output as
   static text (copy-pasteable, screen-reader friendly) in addition to the cast.
4. **Runs `token-finops report --compact`.** **The aha moment:** two progress bars about
   their own real usage plus a runway. If Claude Code shows "quota via status-line hook
   needed", the page must immediately link to the status line page rather than leaving them
   with a half-empty report.
5. **Clicks "report" in the nav** because the homepage teased `--compact` and they want the
   full picture (budget/window/pace/burn/runway, `--budget`, `--watch`). This is where
   "runway" and "binding constraint" get their real explanations, next to the full
   `01-report.cast`.
6. **Maybe clicks "status line"** if they live in tmux/starship — this is the natural second
   page for the subset of first-timers who arrived from a screenshot of someone's status bar.

### Where a first-timer bounces today

- **Install mismatch** (PyPI 0.2.0 vs docs showing 0.3.x commands) — bounce with prejudice.
- **Empty adapters table** — they run only, say, Cursor (reference-only, ADR 0008) or their
  tool writes no telemetry. The homepage needs one line: "supported today: Copilot CLI,
  Claude Code, Codex, Gemini CLI, Hermes, OpenCode/Kilo, Cline/Roo/Kilo, Aider,
  Continue.dev" so the mismatch is discovered *before* installing, plus a "nothing found?"
  pointer to `synth` ("try it on fake data anyway") — this is the genuinely good first-timer
  use of the synth page.
- **Claude Code quota confusion** — `report --tool claude_code` needs two status-line
  snapshots before burn/runway appear. A first-timer who wires the hook and immediately
  reruns sees incomplete output and concludes it's broken. Both the report page and the
  status line page need the sentence "two snapshots in the same window are enough — use
  Claude Code for a few minutes, then re-run."
- **Savings page taken as a promise** — the estimator is deliberately honest (capex
  amortized on actual inference, solar at forgone feed-in tariff, only Haiku/Sonnet-class
  work counts as replaceable). A skimmer sees "$8.86/1M local" without caveats and either
  over-believes or dismisses it. Keep savings low in the nav and lead the page with the
  break-even framing, not the per-token number.

### Homepage vs. sub-page split for this persona

**Homepage:** pitch, trust bullets, supported-tools list, quickstart (3 commands + static
output), ONE cast (`01`), install instructions, "nothing found?" escape hatch, one-line
definitions of runway + binding constraint, links out. **Not on the homepage:** full report
anatomy, status-line formats, self-audit dedup logic, savings methodology, env-var table —
all sub-page material. The current single long page fails precisely because all of that sits
between the pitch and the quickstart.

---

## Persona 2: the power user

**Who:** installed weeks ago, `collect-statusline` wired into Claude Code, `status --format
tmux` in their bar, runs `report` habitually, maybe committed a fix. They never read the
homepage again. They arrive at the docs via search or a nav click with a **specific
question**, and today the answer is scattered across `token-finops-cli/README.md`, root
`README.md`, `docs/TMUX.md`, `docs/INTEGRATIONS.md`, `docs/USECASES.md`, `docs/adr/*`, and
`claude-tasks.md` — none of which the docs site currently signposts.

### What they've internalized vs. what they look up

Internalized: install, `adapters`, `report --compact`, what runway means. What they come
back for — the "level 2" concepts:

1. **Scripting `--json`** — `report --json`, `self-audit --json` (documented "for CI/PR
   checklists"), `status --format json/waybar`. No page today shows the JSON shape or a jq
   example. This is the single most-wanted missing content for this persona.
2. **Self-audit depth** — dedup on `(message.id, requestId)` (naive counting over-reports
   ~1.9x), sub-agent transcript inclusion, by-model breakdown, `--session <id-prefix>`,
   the "sub-agents = 30% of cost" line. `03-self-audit.cast` shows it; the *why it's
   trustworthy* (dedup rationale) is what a power user actually wants explained.
3. **Cache discipline** — `~/.token-finops/last.json`, `--fresh`, `--max-age`, the
   one-refresher-many-widgets pattern (`contrib/refresh/`). Currently buried in
   `docs/TMUX.md`; the status line page should own it.
4. **Env-var overrides** — the full table in `token-finops-cli/README.md` (pointing adapters
   at non-default homes, `TOKEN_FINOPS_HARDWARE_JSON`/`ENERGY_JSON` for measured savings
   inputs). Power users editing `savings/hardware_profiles.json` with their own wattmeter
   numbers is an explicitly supported workflow — say so on the savings page.
5. **Per-adapter caveats** — Aider timestamps approximate, Continue.dev low confidence,
   Codex writes its quota % to disk itself, Hermes local models flagged. The ADRs
   (`docs/adr/`) hold this; the site never links them.
6. **What's coming** — `--online` quota fetchers (T-03), Prometheus textfile exporter
   (T-12), editor plugins nvim/VS Code/Emacs (T-08/09/10), desktop notifications (T-11),
   Claude Code `/runway` skill (T-04). Power users go looking for these; today they only
   find them by reading `claude-tasks.md` in the repo. A short honest "roadmap" block
   prevents both duplicate feature requests and "does it do Prometheus? no? bounce."

### Step-by-step journey (target design)

1. **Arrives with a question** ("how do I get runway into waybar without hammering my
   Claude projects dir?"), clicks **status line** directly. Finds: all four formats,
   `02-status-formats.cast`, and — must-add — the cache/refresher pattern with the
   `contrib/tmux/token-finops.tmux` and `contrib/refresh/` pointers.
2. **Next week:** "my session felt expensive, was it the sub-agents?" → **self-audit** page.
   Finds the dedup explanation, by-model table, `--json`. Aha moment #2 for this persona:
   *"the model, not the raw token count, decides the cost"* — that sentence from the README
   belongs verbatim on the page.
3. **Next month:** "would an M4 Max box pay off for my actual usage?" → **savings** page →
   `break-even --since 90d` against their real history, then edits the hardware JSON with
   measured wattage. The page must present `savings --list` and the JSON-override env vars.
4. **Ongoing:** "can it export to Prometheus / fetch quota online?" → today: dead end, digs
   through the repo. Target: a **reference/roadmap** section (see recommendations) linking
   USECASES.md, the env-var table, ADRs, and the named backlog items.

### Where power users dig today (signposting gaps)

| Question | Lives today | Should be reachable from |
|---|---|---|
| JSON output shapes | nowhere (only `--json` flags mentioned) | report + self-audit + status line pages |
| cache/refresher pattern | `docs/TMUX.md` | status line page |
| env-var override table | `token-finops-cli/README.md` | reference section/page |
| adapter trust levels & caveats | `docs/adr/*`, root README table | report page footnote + reference |
| editor integrations design | `docs/INTEGRATIONS.md` (concept) | status line page ("planned" box) |
| roadmap (T-03, T-12, …) | `claude-tasks.md` | reference/roadmap block |
| every runnable example | `docs/USECASES.md` | nav footer / reference |

---

## Nav order: is the given order right?

Given: overview/install → report → status line → self-audit → savings → synth.

**Verdict: keep the first two and the last one; the middle is right for power users and
acceptable for first-timers — one swap is defensible but not required.**

- **overview/install first** — correct for both personas; power users ignore it.
- **report second** — correct. It is the tool's core question and the natural "learn more"
  click from the homepage teaser.
- **status line third** — correct. It is the highest-traffic power-user page and the
  natural "make it ambient" next step for a convinced first-timer. Daily-visibility
  integrations are the tool's stated purpose (`docs/INTEGRATIONS.md`).
- **self-audit fourth** — correct position, wrong label. It is Claude-Code-specific and
  deep; a first-timer should not hit it before status line. Rename in the nav to
  **"self-audit (session cost)"** or subtitle the page "what did this Claude Code session
  cost?" so the nav itself teaches the term.
- **savings fifth** — correct. It is the "question people ask next", not first, and its
  caveats need the reader already trusting the tool's honesty.
- **synth last** — correct. It is demo/dev tooling. But cross-link it from the homepage's
  "nothing found?" escape hatch, because that is when a first-timer actually needs it.

---

## Recommended next steps (prioritized, implementable)

Ordered by impact; each references the actual pages of the multi-page site.

1. **Homepage (overview/install): enforce the 60-second structure.** Order: one-sentence
   pitch → trust bullets (read-only, offline, stdlib-only, no keys) → supported-tools
   one-liner (all 9 by name) → 3-command quickstart with static copy-pasteable output of
   `adapters` and `report --compact` → embedded `01-report.cast` → install block →
   "nothing found?" box linking to the synth page. Move everything else off the homepage.
2. **Homepage install block: state the PyPI truth.** Until T-05 ships, show
   install-from-checkout as primary (mirroring `docs/INSTALL.md`) with an explicit "PyPI
   still serves 0.2.0 (Copilot-only)" note; place `06-install-pip.cast` here, not as hero.
   Add a checklist item to flip this block when 0.3.0 is published and cast 06 re-recorded
   (T-13).
3. **Report page: define the vocabulary where it appears.** Annotated walkthrough of the
   full report (budget / window / pace / burn / runway lines), a plain-words definition of
   "binding constraint" and "never summed" next to the compact output, the Claude Code
   "two snapshots needed" caveat with a link to the status line page, and a documented
   `report --json` example with the actual JSON shape.
4. **Status line page: own the cache/refresher pattern.** Pull the
   one-refresher-many-widgets content out of `docs/TMUX.md` onto the page:
   `~/.token-finops/last.json`, `--fresh`, `--max-age`, `contrib/refresh/`,
   `contrib/tmux/token-finops.tmux`. Include the `collect-statusline` settings.json snippet
   for Claude Code (it currently lives only in the CLI README). Add a short "planned"
   box naming T-08/T-09/T-10/T-11/T-12 as backlog, linking `claude-tasks.md`.
5. **Self-audit page: lead with trust, rename in nav.** Nav label "self-audit (session
   cost)". Page leads with the dedup rationale (one line per content block → ~1.9x
   over-report → dedup on `(message.id, requestId)`), then by-model and sub-agent
   breakdowns (`03-self-audit.cast`), then `--json` for CI with example output.
6. **Add a reference section (footer on every page, or a compact 7th nav item "reference").**
   Links with one-line descriptions to: env-var override table, `docs/USECASES.md`,
   `docs/adr/` (per-adapter caveats and trust levels), `docs/INTEGRATIONS.md` (design doc),
   `claude-tasks.md` (roadmap: T-03 `--online`, T-12 Prometheus, editor plugins). This
   single addition closes most power-user signposting gaps without new prose.
7. **Savings page: lead with break-even, surface the override workflow.** Order:
   break-even against real history (`04-savings-break-even.cast`) → per-token comparison →
   the three honesty caveats (capex amortized on actual inference, solar at forgone
   feed-in tariff, only Haiku/Sonnet-class replaceable) → "measure your own box":
   `savings --list`, editing `hardware_profiles.json`/`energy.json`,
   `TOKEN_FINOPS_HARDWARE_JSON`/`TOKEN_FINOPS_ENERGY_JSON`.
8. **Synth page: frame for its two real audiences.** (a) first-timers with an empty
   adapters table ("try the whole CLI on fake data in one command", `--print-env`
   one-liner, `05-synth.cast`), (b) contributors/demo-recorders (scenario list from
   `docs/SYNTH.md`). Cross-link (a) from the homepage escape hatch.
9. **Per-page "who is this for" subtitle.** One line under each page title (e.g. self-audit:
   "Claude Code users: what a session actually cost, by model and sub-agent") so nav
   misclicks self-correct in two seconds.
10. **Adapter-status honesty row on the report page.** Compact version of the root README's
    status column (Aider timestamps approximate, Continue.dev low confidence, Cursor/
    Windsurf/Ollama reference-only) with links to the corresponding ADRs — pre-empts the
    power user's "why is my Aider runway weird" dig.
