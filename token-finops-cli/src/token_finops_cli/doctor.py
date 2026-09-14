"""`token-finops doctor` — "why is my report empty?", answered per adapter.

`adapters` already answers *what was probed*; `doctor` answers *what to do
about it*. For every registered adapter it reports one of three states:

  found    the adapter's scan() returned events -> `report` has data for it
  empty    the tool's own data location exists, but there is no usage in it
           yet (installed, never used, or used before the current data dir)
  missing  none of the probed locations exist -> the coding agent itself
           does not look installed on this machine

Path probing is *not* reimplemented here: each diagnosis calls back into the
adapter's own discovery helpers (`_search_roots()`, `_roots()`, `db_paths`,
`sessions_dir`, `db_path`, `root`) so doctor can never drift from what
`report` actually reads.

Exit code is always 0. This is a diagnostic, not a health check: "no coding
agent installed" and "installed but no usage yet" are both perfectly normal
states for a fresh machine, and a non-zero exit would make `doctor` unusable
in a shell prompt or a CI setup step that just wants the text. Failures that
*are* exceptional (an unreadable path, a corrupt store) surface as a per-tool
note, not as a process-level failure.
"""
from __future__ import annotations

import os
import platform
import sqlite3
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from . import __version__
from .report import fmt_dt

# Per-tool copy. Each entry is (what the tool is, how to get usage into it).
# `install` deliberately points at the repo's install guide instead of
# repeating package names that may drift; `use` is the concrete next action
# that makes the adapter's data appear.
_HINTS = {
    "copilot": {
        "missing": "GitHub Copilot CLI writes ~/.copilot/session-store.db on first run. "
                   "Install it (`npm install -g @github/copilot`, Node 22+) or set "
                   "TOKEN_FINOPS_COPILOT_DB to an existing session-store.db.",
        "empty": "Copilot CLI is installed but assistant_usage_events is empty — run `copilot` "
                 "and send one prompt, then re-run doctor.",
        "found": "Add your plan's monthly AI-unit allowance: `token-finops report --tool copilot "
                 "--budget N --cycle-day D`.",
    },
    "claude_code": {
        "missing": "No Claude Code transcripts. Install Claude Code (`brew install --cask claude-code` "
                   "or `npm install -g @anthropic-ai/claude-code`), or point CLAUDE_CONFIG_DIR at the "
                   "config dir you actually use.",
        "empty": "Claude Code's config dir exists but holds no session transcripts yet — run one "
                 "Claude Code session, then `token-finops self-audit`.",
        "found": "5h/7d quota percentages only exist in the status line: wire "
                 "`token-finops collect-statusline` as statusLine.command in ~/.claude/settings.json.",
    },
    "codex": {
        "missing": "No ~/.codex. Install the OpenAI Codex CLI (`brew install --cask codex` or "
                   "`npm install -g @openai/codex`), or set CODEX_HOME.",
        "empty": "Codex CLI's home exists but has no rollout-*.jsonl sessions — run `codex` once.",
        "found": "Codex records its own rate limits; `token-finops report --tool codex` shows the "
                 "5h/7d windows straight from the newest rollout.",
    },
    "gemini_cli": {
        "missing": "No ~/.gemini. Install the Gemini CLI (`brew install gemini-cli` or "
                   "`npm install -g @google/gemini-cli`), or set GEMINI_CLI_HOME.",
        "empty": "Gemini CLI's home exists but no chats were found under tmp/*/chats — run `gemini` once.",
        "found": "Gemini quotas are request-based; override the daily allowance with "
                 "`token-finops report --tool gemini_cli --allowance N`.",
    },
    "hermes": {
        "missing": "No ~/.hermes/state.db. Install Hermes Agent (see docs/INSTALL.md) or set HERMES_HOME.",
        "empty": "Hermes' state.db exists but has no session usage rows yet — run one Hermes session.",
        "found": "Hermes records per-model billing mode; local-model events carry no USD by design.",
    },
    "opencode": {
        "missing": "No OpenCode/Kilo database. Install OpenCode (`brew install opencode` or "
                   "`npm install -g opencode-ai@latest`) / Kilo CLI (`npm install -g @kilocode/cli`), "
                   "or set TOKEN_FINOPS_OPENCODE_DB to the .db you use.",
        "empty": "The OpenCode/Kilo database exists but holds no messages yet — run one session.",
        "found": "OpenCode and Kilo share this adapter; events are tagged with the source database.",
    },
    "cline": {
        "missing": "Cline / Roo / Kilo are VS Code extensions, not CLIs — install one from the VS Code "
                   "marketplace (the editor itself via `brew install --cask visual-studio-code`). If your "
                   "editor data lives elsewhere, set TOKEN_FINOPS_CLINE_DIRS to its globalStorage dir(s).",
        "empty": "A VS Code globalStorage dir exists but holds no Cline/Roo/Kilo task history — start a "
                 "task in the extension, or check that the right editor profile is being probed.",
        "found": "Tasks without a recorded `cost` fall back to an estimate from the model's list price.",
    },
    "aider": {
        "missing": "No Aider history found. Aider writes .aider.chat.history.md into each project "
                   "directory it runs in, so it is only found under the roots probed above — set "
                   "TOKEN_FINOPS_AIDER_DIRS to the parent dir of your projects (colon-separated). "
                   "Install Aider with `pipx install aider-chat` (see https://aider.chat).",
        "empty": "Aider's analytics file exists but no chat history was found under the probed roots — "
                 "point TOKEN_FINOPS_AIDER_DIRS at the directories you actually run Aider in.",
        "found": "Aider costs come from its own chat-history lines; if you enabled Aider's analytics, "
                 "TOKEN_FINOPS_AIDER_ANALYTICS adds that file as a second source.",
    },
    "continue": {
        "missing": "No ~/.continue/sessions. Install the Continue.dev extension in your editor, or set "
                   "CONTINUE_GLOBAL_DIR if you use a non-default profile.",
        "empty": "Continue.dev's sessions dir exists but is empty — have one chat in the extension.",
        "found": "Continue sessions carry per-message token counts; USD is a list-price estimate.",
    },
}

_GENERIC = {
    "missing": "Not found on this machine — install the tool, or point its override environment "
               "variable at an existing data location.",
    "empty": "Data location exists but holds no usage yet — run the tool once.",
    "found": "Data found; `token-finops report` includes this tool.",
}

# The override env var per tool, printed with the probed paths so a user with a
# non-standard install knows exactly which knob to turn.
_ENV_VARS = {
    "copilot": "TOKEN_FINOPS_COPILOT_DB",
    "claude_code": "CLAUDE_CONFIG_DIR",
    "codex": "CODEX_HOME",
    "gemini_cli": "GEMINI_CLI_HOME",
    "hermes": "HERMES_HOME",
    "opencode": "TOKEN_FINOPS_OPENCODE_DB",
    "cline": "TOKEN_FINOPS_CLINE_DIRS",
    "aider": "TOKEN_FINOPS_AIDER_DIRS",
    "continue": "CONTINUE_GLOBAL_DIR",
}


@dataclass
class Diagnosis:
    tool: str
    display_name: str
    status: str                       # "found" | "empty" | "missing"
    paths: list[tuple[str, bool]] = field(default_factory=list)   # (path, exists)
    events: int = 0
    latest: Optional[datetime] = None
    note: str = ""                    # only set when scanning raised

    @property
    def hint(self) -> str:
        return _HINTS.get(self.tool, _GENERIC).get(self.status, _GENERIC[self.status])


def _tilde(path: str) -> str:
    """Render an absolute path with $HOME collapsed back to `~`."""
    home = os.path.expanduser("~")
    if home and path.startswith(home):
        return "~" + path[len(home):]
    return path


def probe_paths(ad) -> list[str]:
    """Every location this adapter looks at, using the adapter's own discovery
    helpers rather than a second copy of the path rules."""
    paths: list[str] = []
    if ad.tool == "aider":
        from .adapters.aider import _search_roots
        paths.extend(os.path.expanduser(p) for p in _search_roots())
        paths.append(ad._analytics_path())
    elif ad.tool == "cline":
        paths.extend(ad._roots())
        paths.append(os.path.expanduser(os.environ.get("CLINE_CLI_HOME", "~/.cline")))
    elif ad.tool == "opencode":
        paths.extend(ad.db_paths)
    elif ad.tool == "continue":
        paths.append(ad.sessions_dir)
    elif ad.tool == "hermes":
        paths.append(ad.db_path)
    else:
        paths.append(ad.root)
    # de-duplicate, keep order
    seen: set[str] = set()
    return [p for p in paths if not (p in seen or seen.add(p))]


def _installed(ad) -> bool:
    """Does the *tool* look installed, independent of whether it has usage?

    `ad.available()` is the answer for every adapter except Aider, whose
    default search root is `~` — which always exists, so `available()` would
    call Aider installed on every machine on earth. For Aider the evidence is
    its opt-in analytics file (the only Aider-owned path we probe); chat
    history living somewhere under the search roots shows up as events.
    """
    if ad.tool == "aider":
        return os.path.exists(ad._analytics_path())
    try:
        return bool(ad.available())
    except OSError:
        return False


def diagnose(ad) -> Diagnosis:
    """One adapter -> one Diagnosis. Never raises: a broken store is a note."""
    paths = [(p, os.path.exists(p)) for p in probe_paths(ad)]
    events: list = []
    note = ""
    try:
        events = ad.events()
    except (OSError, ValueError, sqlite3.Error) as exc:   # corrupt/unreadable store
        note = f"scan failed: {type(exc).__name__}: {exc}"

    if events:
        status = "found"
    elif _installed(ad):
        status = "empty"
    else:
        status = "missing"
    return Diagnosis(
        tool=ad.tool, display_name=ad.display_name, status=status, paths=paths,
        events=len(events), latest=events[-1].ts_utc if events else None, note=note,
    )


def _wrap(label: str, text: str, width: int = 96) -> list[str]:
    """`      label:  <text>` with continuation lines aligned under the text."""
    indent = " " * 14
    body = textwrap.wrap(text, width=width) or [""]
    return [f"      {label + ':':<8}{body[0]}"] + [indent + line for line in body[1:]]


def render(diags: list[Diagnosis]) -> str:
    lines = ["token-finops doctor — what `report` can and cannot see on this machine", ""]
    lines.append(f"  token-finops-cli {__version__}")
    lines.append(f"  Python {platform.python_version()} ({sys.executable})")
    lines.append(f"  platform {platform.system()} {platform.release()}")
    lines.append("")

    for d in diags:
        head = f"  [{d.status}]".ljust(12) + f"{d.display_name} ({d.tool})"
        if d.status == "found":
            head += f" — {d.events} events, latest {fmt_dt(d.latest)}"
        lines.append(head)
        for path, exists in d.paths:
            lines.append(f"      probed: {_tilde(path)}  ({'exists' if exists else 'not found'})")
        env = _ENV_VARS.get(d.tool)
        if env:
            override = os.environ.get(env)
            if override:
                lines.append(f"      {env}={override} (override active)")
        if d.note:
            lines.extend(_wrap("note", d.note))
        lines.extend(_wrap("hint", d.hint))
        lines.append("")

    found = sum(1 for d in diags if d.status == "found")
    empty = sum(1 for d in diags if d.status == "empty")
    missing = sum(1 for d in diags if d.status == "missing")
    lines.append(f"  summary: {found} with data, {empty} installed but no usage yet, {missing} not found")
    lines.append("")
    if found == 0:
        lines.append("  Nothing to report on yet — that is expected on a fresh machine.")
    lines.append("  Want to see what the tool does without waiting for real usage? Run it on")
    lines.append("  synthetic demo data (nothing real is read or written):")
    lines.append("")
    lines.append("      token-finops synth --out ./demo-home --scenario steady")
    lines.append("      eval \"$(token-finops synth --out ./demo-home --scenario steady --print-env)\"")
    lines.append("      token-finops report")
    return "\n".join(lines)


def cmd_doctor(args) -> str:
    from .adapters import all_adapters

    ads = all_adapters()
    tool_filter = getattr(args, "tool", None)
    if tool_filter:
        ads = [a for a in ads if a.tool in tool_filter]
    return render([diagnose(ad) for ad in ads])
