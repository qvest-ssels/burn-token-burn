"""token-finops command line.

    token-finops report   [--tool copilot|claude_code|codex|gemini_cli|hermes] [--compact] [--watch N] [--json]
                          [--budget N] [--cycle-day D]           # Copilot allowance / cycle
    token-finops sessions [--tool T] [--since 7d] [--limit 20]
    token-finops self-audit [--session ID|latest] [--config-dir ~/.claude]  # Claude Code, incl. sub-agents
    token-finops savings  ...                                     # see savings/local_estimator.py
    token-finops break-even ...
    token-finops collect-statusline                              # Claude Code statusLine.command hook
    token-finops adapters                                        # what data sources were found
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .adapters import all_adapters
from .adapters.base import registry
from .core.runway import binding_constraint, compute_runway
from .report import (compact_line, fmt_days, fmt_dt, fmt_tokens, fmt_usd, render_by_model,
                     render_runway, render_sessions_table, render_summary, summarize)

SINCE_MAP = {"1d": timedelta(days=1), "7d": timedelta(days=7), "30d": timedelta(days=30), "all": None}


def _since(arg: str):
    d = SINCE_MAP[arg]
    return None if d is None else datetime.now(timezone.utc) - d


def _adapters(tool_filter):
    ads = all_adapters()
    if tool_filter:
        ads = [a for a in ads if a.tool in tool_filter]
    return ads


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def cmd_report(args) -> str:
    lines: list[str] = []
    runways = []
    payload = []
    for ad in _adapters(args.tool):
        if not ad.available():
            continue
        if ad.tool == "copilot":
            policy = ad.default_policy(args.budget, cycle_day=args.cycle_day)
        else:
            policy = ad.default_policy(args.allowance)
        events = ad.events(since=None)
        quota = ad.quota()
        history = ad.quota_history() if hasattr(ad, "quota_history") else None
        rw = compute_runway(events, policy, quota=quota, quota_history=history)
        runways.append((ad, rw, events))
        payload.append(_runway_json(ad, rw))
        if args.compact:
            lines.append(compact_line(rw, ad.display_name))
        else:
            if lines:
                lines.append("")
            lines += render_summary(f"{ad.display_name} (last 7d)",
                                    [e for e in events if e.ts_utc >= _since("7d")])
            lines.append("")
            lines += render_runway(rw, ad.display_name)
    if not runways:
        return "No supported tool data found. Run `token-finops adapters` to see what was probed."
    if args.json:
        return json.dumps(payload, indent=2, default=str)
    binding = binding_constraint([rw for _, rw, _ in runways])
    if binding and len(runways) > 1:
        lines.append("")
        name = next(ad.display_name for ad, rw, _ in runways if rw is binding)
        lines.append(f"binding constraint: {name} ({binding.window_id}) — runway {fmt_days(binding.runway_days)} -> {binding.status.value}")
    return "\n".join(lines)


def _runway_json(ad, rw) -> dict:
    return {
        "tool": ad.tool, "display_name": ad.display_name, "window": rw.window_id,
        "unit": rw.unit.value, "used": rw.used, "allowance": rw.allowance,
        "used_fraction": rw.used_fraction, "time_fraction": rw.time_fraction,
        "pace_ratio": rw.pace_ratio, "burn_per_day_avg": rw.burn_per_day_avg,
        "burn_per_day_ema": rw.burn_per_day_ema, "runway_days": rw.runway_days,
        "days_left": rw.days_left, "resets_at": rw.resets_at, "status": rw.status.value,
        "notes": rw.notes,
    }


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #
def cmd_sessions(args) -> str:
    lines = []
    for ad in _adapters(args.tool):
        if not ad.available():
            continue
        events = ad.events(since=_since(args.since))
        if not events:
            continue
        lines.append(f"{ad.display_name} sessions ({'all time' if args.since == 'all' else 'last ' + args.since}):")
        lines += render_sessions_table(events, args.limit)
        lines.append("")
    return "\n".join(lines) or "No sessions found."


# --------------------------------------------------------------------------- #
# self-audit (Claude Code, incl. sub-agents)
# --------------------------------------------------------------------------- #
BUCKETS = [
    ("Claude in Chrome", lambda t: t.startswith("mcp__claude-in-chrome__")),
    ("Connectors (MCP)", lambda t: t.startswith("mcp__")),
    ("Web research", lambda t: t in ("WebSearch", "WebFetch")),
    ("File & shell ops", lambda t: t in ("Read", "Write", "Edit", "Glob", "Grep", "Bash", "NotebookEdit")),
    ("Sub-agent launches", lambda t: t == "Agent"),
    ("Other tools", lambda t: bool(t)),
    ("Text / reasoning", lambda t: not t),
]


def _bucket(first_tool: str) -> str:
    for name, pred in BUCKETS:
        if pred(first_tool):
            return name
    return "Other tools"


def cmd_self_audit(args) -> str:
    from .adapters.claude_code import ClaudeCodeAdapter, five_hour_blocks

    root = os.path.join(os.path.expanduser(args.config_dir), "projects") if args.config_dir else None
    ad = ClaudeCodeAdapter(root)
    if not ad.available():
        return f"No Claude Code transcripts under {ad.root}"
    events = ad.events()
    if not events:
        return "No usage events found."

    # pick session
    sessions = defaultdict(list)
    for e in events:
        sessions[e.session_id].append(e)
    if args.session in (None, "latest"):
        sid = max(sessions, key=lambda s: max(e.ts_utc for e in sessions[s]))
    else:
        matches = [s for s in sessions if s.startswith(args.session)]
        if not matches:
            return f"No session starting with {args.session!r}. Known: {', '.join(sorted(sessions))[:400]}"
        sid = matches[0]
    evs = sorted(sessions[sid], key=lambda e: e.ts_utc)
    main = [e for e in evs if not e.agent_id]
    subs = [e for e in evs if e.agent_id]

    out: list[str] = []
    out.append(f"Self-audit: Claude Code session {sid}")
    out.append(f"  span: {fmt_dt(evs[0].ts_utc)} -> {fmt_dt(evs[-1].ts_utc)}")
    out.append(f"  API calls (deduplicated): {len(evs)}  = main loop {len(main)} + sub-agents {len(subs)}")
    out.append("")
    out += render_summary("Totals (main + sub-agents)", evs)
    out.append("")
    out.append("By model (the thing that actually decides the bill):")
    out += render_by_model(evs)

    if subs:
        out.append("")
        out.append("Sub-agents:")
        by_agent = defaultdict(list)
        for e in subs:
            by_agent[e.agent_id].append(e)
        out.append(f"  {'agent':<20} {'model':<20} {'calls':>6} {'tokens':>9} {'API-eq $':>9}")
        for aid, aev in sorted(by_agent.items(), key=lambda kv: -summarize(kv[1])['usd']):
            s = summarize(aev)
            tot = s["input"] + s["output"] + s["cache_read"] + s["cache_write"]
            models = ",".join(sorted({e.model_norm for e in aev}))
            out.append(f"  {aid:<20} {models:<20} {s['calls']:>6} {fmt_tokens(tot):>9} {s['usd']:>9.2f}")
        s_main, s_sub = summarize(main), summarize(subs)
        if s_main["usd"] + s_sub["usd"] > 0:
            share = s_sub["usd"] / (s_main["usd"] + s_sub["usd"]) * 100
            out.append(f"  sub-agents = {share:.0f}% of API-equivalent cost")

    out.append("")
    out.append("By activity (main loop, bucketed by the first tool called in each turn):")
    buckets = defaultdict(list)
    for e in main:
        buckets[_bucket(e.tags.get("first_tool", ""))].append(e)
    total_usd = sum(summarize(v)["usd"] for v in buckets.values()) or 1.0
    out.append(f"  {'activity':<22} {'turns':>6} {'API-eq $':>10} {'share':>6}")
    for name, bev in sorted(buckets.items(), key=lambda kv: -summarize(kv[1])["usd"]):
        s = summarize(bev)
        out.append(f"  {name:<22} {s['calls']:>6} {s['usd']:>10.2f} {s['usd'] / total_usd * 100:>5.0f}%")

    blocks = five_hour_blocks(evs)
    out.append("")
    out.append(f"5-hour billing blocks touched: {len(blocks)}")
    for b in blocks[-5:]:
        out.append(f"  {b['start']:%Y-%m-%d %H:%M} -> {b['end']:%H:%M} UTC  calls {len(b['events']):>4}  "
                   f"tokens {fmt_tokens(b['tokens']):>7}  API-eq {fmt_usd(b['usd'])}")

    out.append("")
    out.append("Note: 'API-equivalent' prices the calls at pay-per-token list prices "
               "(see core/pricing.py, reviewed " + _pricing_date() + "). On a subscription the real "
               "constraint is the rolling 5h/7d window, not dollars.")
    if args.json:
        return json.dumps({"session": sid, "calls": len(evs), "main": len(main), "subagents": len(subs),
                           "by_model": {m: {k: v for k, v in s.items() if k not in ('sessions', 'agents')}
                                        for m, s in dict(_by_model_json(evs)).items()}},
                          indent=2, default=str)
    return "\n".join(out)


def _by_model_json(evs):
    from .report import by_model
    return by_model(evs)


def _pricing_date() -> str:
    from .core.pricing import PRICING_REVIEW_DATE
    return PRICING_REVIEW_DATE


# --------------------------------------------------------------------------- #
# collect-statusline (Claude Code hook)
# --------------------------------------------------------------------------- #
def cmd_collect_statusline(args) -> str:
    """Use as `statusLine.command` in ~/.claude/settings.json. Reads the JSON
    Claude Code pipes in, persists rate_limits to ~/.token-finops/quota.json,
    and prints a one-line status for the status bar."""
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        data = {}
    snap = {"observed_at": datetime.now(timezone.utc).isoformat(), "rate_limits": data.get("rate_limits") or {},
            "model": (data.get("model") or {}).get("id"), "cost": data.get("cost")}
    path = os.path.expanduser("~/.token-finops/quota.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snap, fh)
    if snap["rate_limits"]:
        # append-only history so the runway engine can estimate burn from consecutive snapshots
        with open(os.path.expanduser("~/.token-finops/quota_history.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(snap) + "\n")
    rl = snap["rate_limits"]
    parts = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        w = rl.get(key) or {}
        if w.get("used_percentage") is not None:
            parts.append(f"{label} {w['used_percentage']:.0f}%")
    model = snap.get("model") or ""
    return " | ".join([p for p in [model, *parts] if p]) or "token-finops: no rate_limits in statusline payload"


# --------------------------------------------------------------------------- #
# adapters
# --------------------------------------------------------------------------- #
def cmd_adapters(args) -> str:
    lines = [f"  {'tool':<12} {'found':<6} root"]
    for ad in all_adapters():
        lines.append(f"  {ad.tool:<12} {'yes' if ad.available() else 'no':<6} {ad.root}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="token-finops", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("report", help="usage summary + runway per tool (default)")
    r.add_argument("--tool", action="append", choices=sorted(registry) or None, help="restrict to tool(s)")
    r.add_argument("--budget", type=float, default=None, help="Copilot monthly AI-unit allowance")
    r.add_argument("--cycle-day", type=int, default=1, help="Copilot cycle reset day (default 1, UTC)")
    r.add_argument("--allowance", type=float, default=None, help="allowance for non-Copilot tools (native unit)")
    r.add_argument("--compact", "-c", action="store_true", help="one line per tool")
    r.add_argument("--watch", type=float, default=None, metavar="SECONDS")
    r.add_argument("--json", action="store_true")

    s = sub.add_parser("sessions", help="per-session table")
    s.add_argument("--tool", action="append", choices=sorted(registry) or None)
    s.add_argument("--since", choices=SINCE_MAP.keys(), default="all")
    s.add_argument("--limit", type=int, default=20)

    a = sub.add_parser("self-audit", help="Claude Code: what did one session cost, incl. sub-agents")
    a.add_argument("--session", default="latest", help="session id prefix or 'latest'")
    a.add_argument("--config-dir", default=os.environ.get("CLAUDE_CONFIG_DIR"))
    a.add_argument("--json", action="store_true")

    sub.add_parser("collect-statusline", help="Claude Code statusLine hook: persist rate_limits")
    sub.add_parser("adapters", help="list detected data sources")

    from .savings import add_savings_parsers
    add_savings_parsers(sub)
    return p


def _normalize_argv(argv):
    if not argv:
        return ["report"]
    known = {"report", "sessions", "self-audit", "collect-statusline", "adapters", "savings",
             "break-even", "-h", "--help"}
    return argv if argv[0] in known else ["report", *argv]


def main(argv=None):
    from .adapters import all_adapters as _load  # ensure registry populated before parser
    _load()
    parser = build_parser()
    args = parser.parse_args(_normalize_argv(sys.argv[1:] if argv is None else argv))
    handlers = {"report": cmd_report, "sessions": cmd_sessions, "self-audit": cmd_self_audit,
                "collect-statusline": cmd_collect_statusline, "adapters": cmd_adapters}
    if args.command in ("savings", "break-even"):
        from .savings import cmd_savings, cmd_break_even
        print((cmd_savings if args.command == "savings" else cmd_break_even)(args))
        return
    handler = handlers[args.command]
    if args.command == "report" and args.watch:
        try:
            while True:
                print("\033[2J\033[H", end="")
                print(handler(args))
                print(f"\n(refreshing every {args.watch:.0f}s, Ctrl+C to stop)")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return
    print(handler(args))


if __name__ == "__main__":
    main()
