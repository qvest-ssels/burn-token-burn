"""`token-finops status` — one renderer family for every status surface.

The idea (docs/INTEGRATIONS.md, P0): compute the runway once, cache it in
`~/.token-finops/last.json`, and let tmux, starship, waybar, polybar, i3status,
SwiftBar/xbar, prompts and editors consume that cache in the format they need.
Widgets that poll every few seconds must never each rescan hundreds of MB of
JSONL — `status` reads the cache by default and only rescans with `--fresh`
or when the cache is older than `--max-age` seconds.

Cache contract (stable, `schema_version` bumps on breaking change):
{
  "schema_version": 1,
  "generated_at": "<ISO-8601 UTC>",
  "tools": [ <the same objects `report --json` emits> ],
  "binding": { "tool": ..., "display_name": ..., "runway_days": ..., "status": ... } | null
}
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Optional

SCHEMA_VERSION = 1
CACHE_DIR = os.path.expanduser("~/.token-finops")
CACHE_FILE = os.path.join(CACHE_DIR, "last.json")
LAST_LINE_FILE = os.path.join(CACHE_DIR, "last-line.txt")

SHORT = {"copilot": "CP", "claude_code": "CC", "codex": "CX", "gemini_cli": "GM", "hermes": "HM",
         "opencode": "OC", "cline": "CL", "aider": "AI", "continue_dev": "CT", "continue": "CT"}
GLYPH = {"OK": "", "WARN": "!", "CRITICAL": "!!", "EXHAUSTED": "X", "UNLIMITED": "", "UNKNOWN": "?"}
TMUX_COLOUR = {"OK": "colour2", "WARN": "colour3", "CRITICAL": "colour1", "EXHAUSTED": "colour1",
               "UNLIMITED": "colour8", "UNKNOWN": "colour8"}
HEX_COLOUR = {"OK": "#98c379", "WARN": "#e5c07b", "CRITICAL": "#e06c75", "EXHAUSTED": "#e06c75",
              "UNLIMITED": "#5c6370", "UNKNOWN": "#5c6370"}


def fmt_runway(days) -> str:
    if days is None:
        return "n/a"
    if isinstance(days, float) and math.isinf(days):
        return "inf"
    if days < 1:
        return f"{days * 24:.0f}h"
    return f"{days:.0f}d"


def pct(x) -> str:
    return "?" if x is None else f"{x * 100:.0f}%"


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
def _sanitize(t: dict) -> dict:
    """JSON has no Infinity: an unbounded runway is stored as null (status tells the story)."""
    t = dict(t)
    rd = t.get("runway_days")
    if isinstance(rd, float) and (math.isinf(rd) or math.isnan(rd)):
        t["runway_days"] = None
    return t


def build_snapshot(tools_payload: list[dict]) -> dict:
    """Wrap `report --json` objects into the cache contract."""
    tools_payload = [_sanitize(t) for t in tools_payload]
    cands = [t for t in tools_payload
             if t.get("runway_days") is not None and t.get("status") not in ("UNLIMITED", "UNKNOWN")]
    binding = min(cands, key=lambda t: t["runway_days"]) if cands else None
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tools": tools_payload,
        "binding": None if binding is None else {
            "tool": binding["tool"], "display_name": binding["display_name"],
            "window": binding["window"], "runway_days": binding["runway_days"],
            "used_fraction": binding.get("used_fraction"), "status": binding["status"],
        },
    }


def write_cache(snapshot: dict, path: str = CACHE_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, allow_nan=False, default=str)
    os.replace(tmp, path)
    with open(LAST_LINE_FILE if path == CACHE_FILE else path + ".line", "w", encoding="utf-8") as fh:
        fh.write(render(snapshot, "plain") + "\n")


def read_cache(path: str = CACHE_FILE) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            snap = json.load(fh)
    except (OSError, ValueError):
        return None
    if snap.get("schema_version") != SCHEMA_VERSION:
        return None
    return snap


def stale_seconds(snapshot: dict, now: Optional[datetime] = None) -> Optional[float]:
    try:
        gen = datetime.fromisoformat(snapshot["generated_at"])
    except (KeyError, ValueError):
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - gen).total_seconds())


# --------------------------------------------------------------------------- #
# renderers
# --------------------------------------------------------------------------- #
def _entries(snapshot: dict, tool_filter: Optional[list[str]], show_all: bool = False) -> list[dict]:
    tools = snapshot.get("tools", [])
    if tool_filter:
        tools = [t for t in tools if t["tool"] in tool_filter]
    elif not show_all:
        # usage-only tools without an allowance have nothing to say in a status bar
        tools = [t for t in tools if t.get("status") != "UNLIMITED"]
    return tools


def _runway_of(t: dict) -> str:
    # null runway on an OK tool means "no burn yet" → unbounded, not unknown
    if t.get("runway_days") is None and t.get("status") == "OK":
        return "inf"
    return fmt_runway(t.get("runway_days"))


def _seg(t: dict) -> str:
    return f"{SHORT.get(t['tool'], t['tool'][:2].upper())} {pct(t.get('used_fraction'))} {_runway_of(t)}{GLYPH.get(t['status'], '')}"


def render_plain(snapshot, tools) -> str:
    parts = [_seg(t) for t in tools]
    b = snapshot.get("binding")
    tail = f" | binds: {SHORT.get(b['tool'], b['tool'])}" if b and len(tools) > 1 else ""
    return (" | ".join(parts) or "token-finops: no data") + tail


def render_tmux(snapshot, tools) -> str:
    segs = []
    for t in tools:
        segs.append(f"#[fg={TMUX_COLOUR.get(t['status'], 'default')}]{_seg(t)}#[default]")
    return " ".join(segs) or "token-finops: no data"


def render_starship(snapshot, tools) -> str:
    # starship custom module: plain text; colour comes from the module's `style`.
    b = snapshot.get("binding")
    if b:
        return f"{SHORT.get(b['tool'], b['tool'])} {pct(b.get('used_fraction'))} {_runway_of(b)}{GLYPH.get(b['status'], '')}"
    return render_plain(snapshot, tools)


def render_waybar(snapshot, tools) -> str:
    b = snapshot.get("binding") or (tools[0] if tools else None)
    text = render_plain(snapshot, tools)
    cls = (b["status"].lower() if b else "unknown")
    tooltip = "\n".join(f"{t['display_name']}: {pct(t.get('used_fraction'))} used, runway {_runway_of(t)} ({t['status']})"
                        for t in tools) or "no data"
    frac = (b or {}).get("used_fraction") or 0.0
    return json.dumps({"text": text, "tooltip": tooltip, "class": cls, "percentage": int(min(1.0, frac) * 100)})


def render_polybar(snapshot, tools) -> str:
    return " ".join(f"%{{F{HEX_COLOUR.get(t['status'], '#5c6370')}}}{_seg(t)}%{{F-}}" for t in tools) or "token-finops: no data"


def render_i3(snapshot, tools) -> str:
    # i3status/i3blocks: text line, then optional colour line (i3blocks protocol)
    b = snapshot.get("binding") or (tools[0] if tools else None)
    colour = HEX_COLOUR.get(b["status"], "#5c6370") if b else "#5c6370"
    return f"{render_plain(snapshot, tools)}\n\n{colour}"


def render_xbar(snapshot, tools) -> str:
    """SwiftBar/xbar: first line = menu bar title; after '---' the dropdown."""
    b = snapshot.get("binding")
    title = (f"{SHORT.get(b['tool'], b['tool'])} {_runway_of(b)}{GLYPH.get(b['status'], '')}"
             if b else "tokens")
    colour = f" | color={HEX_COLOUR.get(b['status'])}" if b else ""
    lines = [title + colour, "---"]
    for t in tools:
        lines.append(f"{t['display_name']}: {pct(t.get('used_fraction'))} used · runway {_runway_of(t)} · {t['status']}"
                     f" | color={HEX_COLOUR.get(t['status'], '#5c6370')}")
    age = stale_seconds(snapshot)
    if age is not None:
        lines.append(f"updated {int(age // 60)} min ago | size=11")
    lines.append("Refresh | refresh=true")
    return "\n".join(lines)


def render_json(snapshot, tools) -> str:
    out = dict(snapshot)
    out["tools"] = tools
    out["stale_seconds"] = stale_seconds(snapshot)
    return json.dumps(out, indent=2, allow_nan=False, default=str)


RENDERERS = {"plain": render_plain, "tmux": render_tmux, "starship": render_starship, "waybar": render_waybar,
             "polybar": render_polybar, "i3": render_i3, "xbar": render_xbar, "json": render_json}


def render(snapshot: dict, fmt: str, tool_filter: Optional[list[str]] = None, show_all: bool = False) -> str:
    tools = _entries(snapshot, tool_filter, show_all)
    return RENDERERS[fmt](snapshot, tools)


# --------------------------------------------------------------------------- #
# CLI glue
# --------------------------------------------------------------------------- #
def add_status_parser(sub, parents=None):
    s = sub.add_parser("status", parents=parents or [],
                       help="one-line status for tmux/starship/waybar/… (cached; --fresh to rescan)")
    s.add_argument("--format", "-f", choices=sorted(RENDERERS), default="plain")
    s.add_argument("--tool", action="append", default=None, help="restrict to tool(s)")
    s.add_argument("--all", action="store_true", help="include UNLIMITED (usage-only, no allowance) tools")
    s.add_argument("--fresh", action="store_true", help="rescan telemetry now and refresh the cache")
    s.add_argument("--max-age", type=int, default=300, metavar="SECONDS",
                   help="rescan if the cache is older than this (default 300; 0 = always)")
    s.add_argument("--cache-file", default=None, help="override ~/.token-finops/last.json")
    s.add_argument("--online", action="store_true",
                   help="opt-in: ask the provider for the live quota (implies a rescan; the response "
                        "itself is cached 180s in ~/.token-finops/online-cache.json). Falls back to "
                        "the offline path on any error")
    s.add_argument("--notify", action="store_true",
                   help="desktop notification when the binding constraint's status class changes "
                        "(OK/WARN/CRITICAL/EXHAUSTED); fires only on a class change, never on every "
                        "run. State in ~/.token-finops/notify-state.json")
    s.add_argument("--notify-state-file", default=None, help="override ~/.token-finops/notify-state.json")
    # --budget / --allowance / --cycle-day come from cli.budget_override_parser()


def cmd_status(args) -> str:
    path = args.cache_file or CACHE_FILE
    # `--online` only means something on a rescan: the cached `last.json` was built
    # from whatever quota source the *previous* run used. It therefore implies
    # `--fresh` -- the 180 s online-response cache (online.py) is what keeps a
    # polled status bar from hammering a rate-limited endpoint, not this file.
    snap = None if (args.fresh or getattr(args, "online", False)) else read_cache(path)
    if snap is not None and args.max_age and (stale_seconds(snap) or 0) > args.max_age:
        snap = None
    if snap is None:
        from .cli import collect_report_payload
        snap = build_snapshot(collect_report_payload(args))
        try:
            write_cache(snap, path)
        except OSError:
            pass
    if getattr(args, "notify", False):
        from .notify import STATE_FILE as NOTIFY_STATE_FILE, maybe_notify
        try:
            maybe_notify(snap, args.notify_state_file or NOTIFY_STATE_FILE)
        except OSError:
            pass
    return render(snap, args.format, args.tool, args.all)
