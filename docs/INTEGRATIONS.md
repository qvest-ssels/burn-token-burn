# Integrations: where the runway should actually be visible

Status: **Concept / Phase 5 proposal** — 2026-09-06. No code beyond illustrative snippets.
Prerequisite reading: `docs/PLAN.md` (Phase 4 is the cross-cutting phase), `docs/adr/README.md`.

## The problem this document solves

`token-finops report` answers the right question — *at my current burn rate, does the budget
last until the reset?* — but it answers it only when someone types the command. The failure
mode from the README's opening quote ("somebody burned the whole team's budget") is not a
reporting failure, it is an **attention** failure: nobody looked. A runway number is worth
something only in the seconds *before* you dispatch three frontier sub-agents, and in those
seconds nobody opens a second terminal.

So the design question for Phase 5 is not "which integrations are cool" but: **where is a
developer's gaze already parked, and what is the cheapest honest way to put one number there?**

Three honest constraints shape everything below:

1. **Scanning is not free.** A mature `~/.claude/projects` tree is hundreds of MB of JSONL.
   Fifteen widgets polling every 5 s must not each rescan it. → a single refresher plus a cache.
2. **Most surfaces render text, not logic.** tmux, waybar, starship, SwiftBar all want one
   short string on stdout. → one renderer family, not N ad-hoc formatters.
3. **Some surfaces cannot be reached at all.** Where a target tool has no extension API, say
   so instead of inventing one. Anything below marked *to verify* has **not** been checked
   against current vendor docs and must be before it ships.

---

## 1. Terminal and status surfaces

The cheapest and highest-value tier: the developer already stares at a shell all day.

**tmux `status-right`** (already planned). tmux runs a shell command on an interval and pastes
stdout into the bar. It is the reference consumer for the cached path — it must never scan.

```tmux
set -g status-interval 15
set -g status-right '#(token-finops status --format tmux) | %H:%M'
```

**Starship** supports `[custom.<name>]` modules that run a command and interpolate `$output`
(exact key names *to verify* against the installed starship version). Starship re-renders on
every prompt, i.e. possibly several times a second during a fast edit-run loop — a cached read
is mandatory here, not optional.

**zsh / fish prompt segment.** No plugin needed: a `precmd` hook (zsh) or `fish_right_prompt`
function that `cat`s the cache file and colours it. This is the fallback for people who use
neither tmux nor starship, and it should be a documented recipe, not a maintained plugin —
prompt frameworks (p10k, oh-my-zsh, tide) each want their own segment shape and we do not want
to maintain four.

**Watch pane.** Already shipped: `token-finops report --watch 30 --compact` in a split. This is
the only surface that legitimately *does* rescan, because it is the surface you open when you
actually care. Keep it as the "full truth" view that the one-liners link back to.

## 2. Editors

Editors differ mainly in whether they can run a subprocess asynchronously and render its result
in a status line. Where they can, `--json` is the contract; where they cannot, we are limited to
whatever the cache file contains.

**Neovim** — best fit. A small Lua module (`token-finops.nvim`) with two entry points: a
component function for **lualine**/**heirline**/**mini.statusline**, and a `:TokenFinops`
command opening a scratch buffer with full `report` output. The component must read the cache
file (a synchronous `vim.fn.system()` on every statusline redraw is a well-known way to make
Neovim stutter); refresh via `vim.uv` timer + `vim.system()` async. **LunarVim, AstroNvim,
LazyVim and NvChad need nothing of their own** — they are Neovim configurations and consume the
same Lua module through their normal plugin spec. Saying that explicitly avoids four fake
"integrations" in the README.

**Emacs** — good fit, and the community expects an idiomatic package. Two pieces: a `mode-line`
(or `doom-modeline` segment) showing the binding constraint, and `token-finops.el` providing a
transient/magit-style buffer (`M-x token-finops`) with per-tool detail and `g` to refresh.
Emacs can run the process asynchronously via `make-process`. **Doom and Spacemacs consume the
same package**; no separate work.

**Vim (non-neo)** — degraded but trivial: `statusline` with `%{system('cat ~/.token-finops/last-line.txt')}`
or a timer in Vim 8. Cached data only; document as a recipe.

**Helix** — no plugin API at the time of writing (*to verify* against the current release; a
plugin system has long been in progress). Realistic option today: run the watch pane in a
terminal split beside Helix. Do not promise a Helix statusline component.

**Zed** — has an extension system, but whether extensions may render into the status bar and
spawn arbitrary local processes is *to verify*. Until verified, treat Zed as "document the watch
pane"; if the API allows it, a status-bar extension is a natural M-sized follow-up.

**VS Code** — an extension contributing a `StatusBarItem`, polling the cache and calling
`token-finops report --json` on demand for a detail webview/quick-pick. Worth noting for
positioning: **Cline / Roo / Kilo users already get their numbers through our adapter**
(ADR-0007, parsing `ui_messages.json`) — the extension does not need any cooperation from those
extensions, it just displays what we already read off disk. That is the demo that sells the
extension: usage of *another* extension, surfaced in the same window.

**JetBrains** — a plugin contributing a status-bar widget. Kotlin/Gradle plugin project,
marketplace review, separate release cadence. Technically straightforward, organisationally the
most expensive item on this page; only worth it with evidence of demand.

**Cursor / Windsurf** — reference-only per ADR-0008 and ADR-0011. Cursor is a VS Code fork, so
our VS Code extension may well install and run there, but the numbers it would show are *ours*
(other tools' telemetry), **not Cursor's own usage**, which is server-side and unreliable
locally. Windsurf leaves nothing on disk at all. Any UI here must be explicit about whose budget
it is showing, or it is worse than nothing.

## 3. Agent-native surfaces ("skills")

This is the tier with the most leverage and the least prior art, and it inverts the model:
the consumer is not a human glancing at a bar, it is **the agent itself, asking before it spends**.

The pattern:

> Before dispatching parallel sub-agents on the frontier model, the agent runs
> `token-finops report --json`, reads the binding constraint, and either proceeds, downgrades
> the model, or tells the user "you have 1.9 h of 5 h-window runway left; this fan-out will
> likely exhaust it".

This is exactly the lesson the self-audit in the README already teaches (three research
sub-agents on the frontier model cost more than all the Sonnet work combined) — the integration
makes the lesson operational instead of retrospective.

- **Claude Code** — **shipped** (`contrib/claude-code/`). The status line already existed
  (`collect-statusline`, and it is also how we obtain the provider percentage at all); the
  skill `/runway` is the thing the model can call *mid-task*, where the status line is
  passive. Verified format: a skill is a **directory** containing `SKILL.md` with YAML
  frontmatter (`name`, `description`, `argument-hint`, `allowed-tools`), installed to
  `.claude/skills/runway/` (project) or `~/.claude/skills/runway/` (personal) — a flat
  `runway.md` is not loaded. The body injects the CLI output with `` !`…` `` and the
  `description` is written so Claude invokes it *itself* before a fan-out, not only when a
  human types `/runway`.
- **Codex CLI** — **shipped** (`contrib/codex/`). Verified format: a **custom prompt**, a
  single markdown file with `description`/`argument-hint` frontmatter at
  `~/.codex/prompts/runway.md`, invoked as `/prompts:runway` (the `prompts:` prefix is
  mandatory; it is not a bare slash command). Custom prompts are documented but marked
  deprecated in favour of a newer skills mechanism whose file layout is not stable enough to
  commit against yet — per the rule at the top of this page, we ship the verifiable form and
  say so rather than guessing at the successor. Codex is our best data source anyway: it
  writes `rate_limits` to disk itself (ADR-0003), so the answer is available offline and
  instantly.
- **Copilot CLI** — a `copilot-instructions`-style file describing when to consult the tracker
  is the low-effort version; whether Copilot CLI exposes a first-class custom-command or skill
  mechanism is *to verify*. Instructions alone are already useful: "before large refactors, run
  `token-finops report --tool copilot --compact`".
- **Gemini CLI** — has an extensions/commands mechanism (*to verify* the manifest schema). Fits
  the same `/runway` shape.
- **Hermes Agent** — expose the runway as an agent **tool** the model may call, since Hermes is
  a tool-calling agent framework rather than a slash-command CLI.

All five share one implementation: a stable JSON contract plus a ~20-line wrapper. The
per-agent work is packaging, not logic.

## 4. "Boring" GUI and desktop surfaces

Unglamorous, but this is where a runway warning reaches someone who is *not* currently in a
terminal — and the WARN→CRIT transition is precisely the moment they are not.

| # | Surface | Mechanism | Data |
|---|---|---|---|
| 1 | macOS menu bar | SwiftBar/xbar plugin: an executable named e.g. `tokenfinops.30s.sh` printing menu lines | cached |
| 2 | Raycast | script command (shebang + metadata comments) | cached, `--json` for detail |
| 3 | Alfred | workflow: Script Filter → list of tools | cached |
| 4 | Übersicht | widget: shell command + JSX render on an interval | cached |
| 5 | Windows tray | PowerShell scheduled task + **BurntToast** notification, or a small Python tray app | cached |
| 6 | waybar (Wayland) | `custom/tokenfinops` module, `return-type: json` (`text`/`tooltip`/`class`) | cached |
| 7 | polybar | `custom/script` module with `interval` | cached |
| 8 | i3status / i3blocks | block script printing full/short text + colour | cached |
| 9 | GNOME Argos / Executor | same executable-script convention as xbar | cached |
| 10 | Stream Deck | plugin showing runway on a key; press → open watch pane | cached + on-press scan |
| 11 | Home Assistant | `command_line` sensor running the CLI over SSH or on the HA host | `--json` |
| 12 | Prometheus | node_exporter **textfile collector**: write `.prom` from the same refresher → Grafana | derived from cache |
| 13 | Slack / Teams digest | cron → incoming webhook, daily summary or WARN-only | `--json`, **opt-in** |
| 14 | Obsidian daily note | cron appends a line to today's note (plain file write, no plugin needed) | cached |
| 15 | Desktop notification | `notify-send` / `terminal-notifier` fired by the refresher on status transitions | cached |
| 16 | Apple Shortcuts / iOS widget | Scriptable widget reading a JSON synced via iCloud/Dropbox | cached, **opt-in sync** |
| 17 | Notion / Confluence page | **out of scope** — see below | — |

Notes on three of them. **Prometheus** is the one that gives a team-level view without a server:
the textfile collector is a file drop, so no daemon, no credentials, no network from our side.
**Desktop notifications must be edge-triggered**, on OK→WARN and WARN→CRIT transitions only; a
notification every 30 s trains people to dismiss them. **Notion/Confluence is deliberately out
of scope**: both require an API token and push local usage data to a third-party server, which
contradicts the local-first, credential-free premise of this project (`AGENTS.md` rule 1, and
the no-network default in Phase 4). If a team wants it, the recipe is "point your existing
automation at `report --json`" — we do not ship the token handling.

## 5. Cross-cutting design

### 5.1 One machine-readable contract

`report --json` already emits a per-tool array (`cli.py::_runway_json`). Phase 5 should
**freeze** it as a documented, versioned contract, because fifteen widgets will depend on it:

| Field | Meaning | Stability |
|---|---|---|
| `schema_version` | integer, bumped on breaking change | **new, required** |
| `tool`, `display_name` | adapter id / human label | stable |
| `window`, `unit` | e.g. `5h`, and `percent`/`aiu`/`usd`/`requests` | stable |
| `used`, `allowance`, `used_fraction` | native-unit usage; `allowance` may be `null` | stable |
| `time_fraction`, `pace_ratio` | window elapsed; burn vs. pace | stable |
| `burn_per_day_avg`, `burn_per_day_ema` | pessimistic runway takes the larger | stable |
| `runway_days`, `days_left`, `resets_at` | `runway_days: null` means unbounded (JSON has no `Infinity`) | stable |
| `status` | `OK`/`WARN`/`CRITICAL`/`EXHAUSTED`/`UNLIMITED`/`UNKNOWN` | stable |
| `notes` | free text; **never parse** | unstable by design |
| `binding` | **new**: `true` on the tool that runs out first | proposed |
| `generated_at`, `stale_seconds` | **new**: so a widget can grey out stale data | proposed |

The last one matters more than it looks: a cached widget showing a confident "41 d" from a
crashed refresher two days ago is the one failure mode that destroys trust in the whole tool.

### 5.2 One renderer family

Instead of a shell one-liner per surface, add a subcommand:

```
token-finops status --format tmux|starship|waybar|polybar|i3|xbar|plain|json [--tool T]
```

One code path, one set of tests, per-format quoting/escaping handled once (waybar wants JSON
with `text`/`tooltip`/`class`; tmux wants `#[fg=colour]` sequences; i3blocks wants three lines).
`status` reads the **cache** by default and takes `--fresh` to force a scan. Everything in
sections 1 and 4 then becomes a two-line recipe.

### 5.3 Caching

One writer, many readers:

```
~/.token-finops/last.json      # full report --json payload + generated_at
~/.token-finops/last-line.txt  # pre-rendered plain one-liner for dumb consumers
```

Refreshed by exactly one scheduled job — `systemd --user` timer, launchd agent, Task Scheduler,
or plain cron — at 60–300 s. Widgets never scan. This also gives us the natural place to fire
edge-triggered notifications and to write the Prometheus `.prom` file. It reuses the directory
`collect-statusline` already owns, so there is no new state location to justify.

### 5.4 Privacy

Nothing leaves the machine by default; the cache is local files with user-only permissions.
Every surface that crosses a network boundary — Slack/Teams digest, iOS sync, any hosted
dashboard — is **opt-in, explicitly configured, and documented as such**, consistent with the
`--online` posture in Phase 4. Digests should default to aggregate numbers (runway, status), not
session titles or paths, which can leak client and project names.

### 5.5 What we maintain vs. what we document

An ADR-style decision per integration, using the same tiering logic as the adapter ADRs:

| Tier | Meaning | Members |
|---|---|---|
| **First-party `contrib/`** | in-repo, CI-tested against synthetic data (`token-finops synth`) | `status` renderer, tmux, waybar/polybar, SwiftBar/xbar, Raycast, cache refresher units, Claude Code `/runway` |
| **First-party, separate release** | own repo/registry, own version | `token-finops.nvim`, `token-finops.el`, VS Code extension |
| **Documented recipe** | snippet in docs, no maintenance promise | zsh/fish prompt, Vim, i3status, Argos, Übersicht, Alfred, Home Assistant, Obsidian, Scriptable, Slack digest |
| **Deferred / out of scope** | reasons above | JetBrains (cost), Helix/Zed (API *to verify*), Notion/Confluence (network+token), Stream Deck (niche) |

The recipe tier is the important one: it lets us list twenty surfaces honestly without promising
to keep twenty things working.

## 6. Recommended Phase-5 order

| # | Deliverable | Why first |
|---|---|---|
| 1 | `status --format …` + `~/.token-finops/last.json` cache + refresher units | Every other item is a two-line consumer of it. Nothing else should ship before it. |
| 2 | Claude Code `/runway` skill | Highest leverage: the agent asks *before* spending, and Claude Code is the tool whose window is most often the binding constraint. |
| 3 | tmux + waybar/polybar + SwiftBar recipes in `contrib/` | Our own users' surfaces; near-zero marginal cost once (1) exists; proves the renderer design. |
| 4 | `token-finops.nvim` | Largest editor audience that can be served by one small, testable Lua module. |
| 5 | VS Code status-bar extension | Only way to reach the Cline/Roo/Kilo audience we already parse (ADR-0007), and the first surface for people who never open tmux. |

Emacs package sixth, on the strength of community expectation rather than headcount.
JetBrains only on demand.

### Summary table

| Surface | What it shows | Mechanism | Effort | Priority |
|---|---|---|---|---|
| `status` renderer + cache | — (enabler) | new subcommand + refresher | M | **P0** |
| tmux status-right | binding constraint, 1 line | `#()` shell, cached | S | **P0** |
| Claude Code `/runway` | full compact report + advice | skill/slash command → CLI | S | **P0** |
| starship module | 1 segment | `[custom.*]`, cached | S | P1 |
| zsh/fish prompt | 1 segment | precmd hook, cached | S | P2 (recipe) |
| watch pane | everything | shipped (`--watch`) | — | done |
| Neovim (lualine/heirline) | segment + `:TokenFinops` | Lua module, async `--json` | M | P1 |
| Emacs | mode-line + transient buffer | `token-finops.el` | M | P2 |
| Vim | segment | `system()`, cached | S | P3 (recipe) |
| VS Code | status bar + detail view | extension, `--json` | M | P1 |
| Helix / Zed | — | no verified API | — | deferred |
| JetBrains | status-bar widget | plugin | L | deferred |
| Cursor / Windsurf | *other* tools' usage only | via VS Code ext / none | — | reference-only |
| Codex / Copilot / Gemini / Hermes | runway before fan-out | custom command / tool | S each | P2 |
| macOS menu bar (SwiftBar/xbar) | 1 line + dropdown | plugin script, cached | S | P1 |
| Raycast / Alfred / Übersicht | list or widget | script command | S each | P2/P3 |
| waybar / polybar / i3status | module with colour class | `custom/*`, cached | S | P1 |
| GNOME Argos | menu item | script | S | P3 |
| Windows tray + BurntToast | tray text + toast | PowerShell task | M | P3 |
| Stream Deck | key + press action | plugin SDK | M | deferred |
| Home Assistant | sensor + automations | `command_line`, `--json` | S | P3 |
| Prometheus / Grafana | time series | textfile collector | S | P2 |
| Slack / Teams digest | daily summary | cron + webhook, opt-in | S | P3 |
| Obsidian daily note | one appended line | cron file append | S | P3 |
| Desktop notification | WARN/CRIT transition | notify-send / terminal-notifier | S | P1 |
| iOS widget (Scriptable) | runway on the phone | synced JSON, opt-in | M | P3 |
| Notion / Confluence | — | needs token + network | — | out of scope |

## 7. Open questions

1. **Refresh interval and cost.** What does a full multi-adapter scan actually cost on a large
   real home directory? If it is seconds, the refresher needs incremental scanning (mtime
   watermarks per adapter) before fifteen widgets are a good idea. Measure before promising 60 s.
2. **Staleness policy.** How stale is too stale per surface — grey out, show a `?`, or show the
   last value with an age suffix? Needs one rule, applied by `status`, not per widget.
3. **Which number is *the* number?** The one-line surfaces have room for one value. Binding
   constraint runway is the obvious candidate, but for someone on Copilot-only a percentage may
   read better. Configurable, with a sane default?
4. **`--json` schema versioning.** Do we commit to semver on the payload before v1.0, and how do
   downstream widgets degrade on an unknown `schema_version`?
5. **Extension API facts to verify** before any of it is written: starship custom-module keys;
   Codex CLI custom-command format; Copilot CLI skill mechanism (if any); Gemini CLI extension
   manifest; Zed status-bar/extension capabilities; Helix plugin status; Raycast script-command
   metadata; SwiftBar vs. xbar plugin-API differences.
6. **Do agent skills need a machine-readable *recommendation*,** not just numbers? A field like
   `advice: "downgrade sub-agents to sonnet"` is tempting but embeds policy in the tool; perhaps
   better left to the skill's prompt.
7. **Team aggregation.** Prometheus makes a team view possible. Is that in scope at all, given
   the local-first premise, or does it belong in a separate project?
