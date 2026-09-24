#!/usr/bin/env python3
"""Read an already-exported token-finops usage payload and compare its total
API-equivalent USD against a configured budget.

This intentionally does NOT talk to any adapter or scan `~/.claude`,
`~/.copilot`, etc. — those trees only exist on the machine where the coding
session actually ran, never on a GitHub Actions runner. The payload this
script reads must have been produced *earlier*, by a session that ran
`token-finops self-audit --json` or `token-finops report --json` locally (or
in the same job, before this step) and saved the output to a file — as a
build artifact, a path passed via `usage-json-path`, or a file checked out
from the PR branch. See the accompanying README for the two supported
shapes.

Exit codes:
  0 - usage computed successfully (regardless of whether it is over budget;
      "over budget" is reported via GITHUB_OUTPUT, not a non-zero exit, so
      the composite action can post a PR comment before deciding whether to
      fail the job).
  2 - the input file is missing, is not valid JSON, or does not match either
      of the two known shapes. This is a hard failure distinct from "over
      budget" — something is wrong with the wiring, not with the number.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def load_usage(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def usd_from_self_audit(data: dict) -> tuple[float, str]:
    """`token-finops self-audit --json` shape: {"session", "segments", "calls",
    "main", "subagents", "by_model": {model: {..., "usd": float, ...}}}."""
    by_model = data["by_model"]
    total = sum(float(v.get("usd", 0.0)) for v in by_model.values())
    session = data.get("session", "unknown")
    detail = ", ".join(f"{m} ${v.get('usd', 0.0):.2f}" for m, v in sorted(
        by_model.items(), key=lambda kv: -float(kv[1].get("usd", 0.0))))
    label = f"self-audit session `{session}` ({data.get('calls', '?')} calls" \
            + (f", {data.get('segments')} segments" if data.get("segments", 1) != 1 else "") \
            + f"): {detail or 'no model usage recorded'}"
    return total, label


def usd_from_report(data: list) -> tuple[float, str]:
    """`token-finops report --json` shape: a list of per-tool runway objects
    (`cli.py::_runway_json`). Only rows priced in `usd` contribute to the
    total — rows in `percent`/`aiu`/`requests` have no dollar figure and are
    listed for context only, never coerced into one."""
    usd_rows = [row for row in data if row.get("unit") == "usd"]
    other_rows = [row for row in data if row.get("unit") != "usd"]
    total = sum(float(row.get("used") or 0.0) for row in usd_rows)
    parts = [f"{row.get('display_name', row.get('tool', '?'))} "
             f"${float(row.get('used') or 0.0):.2f} ({row.get('status', '?')})"
             for row in usd_rows]
    if other_rows:
        parts.append("non-USD tools not counted toward budget: " + ", ".join(
            f"{row.get('display_name', row.get('tool', '?'))} ({row.get('status', '?')})"
            for row in other_rows))
    label = "report --json: " + ("; ".join(parts) if parts else "no USD-priced tools found")
    return total, label


def compute_total_usd(data) -> tuple[float, str, str]:
    """Returns (total_usd, source_kind, human_label)."""
    if isinstance(data, dict) and "by_model" in data:
        total, label = usd_from_self_audit(data)
        return total, "self-audit", label
    if isinstance(data, list) and (not data or ("unit" in data[0] and "tool" in data[0])):
        total, label = usd_from_report(data)
        return total, "report", label
    raise ValueError(
        "unrecognised usage JSON shape: expected either the object shape of "
        "`token-finops self-audit --json` (has a top-level \"by_model\" key) "
        "or the list shape of `token-finops report --json` (a list of "
        "objects with \"tool\"/\"unit\" keys)"
    )


def write_output(name: str, value: str) -> None:
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not gh_out:
        # Not running under GitHub Actions (e.g. local/manual testing) -- just print.
        print(f"::set-output name={name}::{value}")
        return
    with open(gh_out, "a", encoding="utf-8") as fh:
        if "\n" in value:
            delim = "TFBC_EOF"
            fh.write(f"{name}<<{delim}\n{value}\n{delim}\n")
        else:
            fh.write(f"{name}={value}\n")


def build_summary(total_usd: float, budget_usd: float, source_kind: str,
                   label: str, over_budget: bool) -> str:
    verdict = "OVER budget" if over_budget else "within budget"
    icon = "\U0001F6A8" if over_budget else "✅"
    lines = [
        "<!-- token-finops-budget-check -->",
        f"### {icon} token-finops budget check",
        "",
        f"**Usage:** ${total_usd:.2f}  **Budget:** ${budget_usd:.2f}  **Verdict:** {verdict}",
        "",
        f"Source: `{source_kind}` payload.",
        "",
        f"- {label}",
        "",
        "_This is an API-equivalent estimate from telemetry exported by a coding-agent "
        "session, not a live billing figure. See the `token-finops` README for what "
        "'API-equivalent' means on a subscription plan._",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--usage-json", required=True, help="Path to a self-audit --json or report --json file")
    p.add_argument("--budget-usd", required=True, type=float, help="Budget threshold in USD")
    args = p.parse_args(argv)

    if not os.path.isfile(args.usage_json):
        print(f"budget-check: usage JSON file not found: {args.usage_json}", file=sys.stderr)
        return 2

    try:
        data = load_usage(args.usage_json)
    except json.JSONDecodeError as exc:
        print(f"budget-check: {args.usage_json} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    try:
        total_usd, source_kind, label = compute_total_usd(data)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"budget-check: {exc}", file=sys.stderr)
        return 2

    over_budget = args.budget_usd > 0 and total_usd > args.budget_usd
    summary = build_summary(total_usd, args.budget_usd, source_kind, label, over_budget)

    print(summary)
    write_output("total-usd", f"{total_usd:.4f}")
    write_output("budget-usd", f"{args.budget_usd:.4f}")
    write_output("over-budget", "true" if over_budget else "false")
    write_output("source-kind", source_kind)
    write_output("summary", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
