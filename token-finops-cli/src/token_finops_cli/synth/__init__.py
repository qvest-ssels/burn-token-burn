"""Unified synthetic telemetry generator.

`generate()` writes a complete, offline, fake-home-directory tree that every
adapter in `token_finops_cli.adapters` can read: Copilot's session-store.db,
Claude Code's project/session/subagent JSONL tree (plus a status-line
`quota.json`/`quota_history.jsonl`), Codex's dated rollout JSONL files, Gemini
CLI's chats tree, Hermes's state.db, OpenCode's opencode.db, the Cline/Roo/Kilo
VS Code globalStorage tree, an Aider chat-history markdown file, and
Continue.dev's sessions tree.

Nothing here invents new on-disk formats: each tool's shape is produced by
that adapter's own `build_synthetic_*()` (see `adapters/<tool>.py`), which
this module imports and calls. The only thing added here is a single entry
point that lays every tool's tree out under one `out_dir` and a shared
`scenario` knob (see `synth.scenarios`) that shapes timestamps/volume the
same way across all of them.

Usage::

    from token_finops_cli.synth import generate
    from token_finops_cli.synth.env import env_for

    manifest = generate("/tmp/demo-home", scenario="burst")
    os.environ.update(env_for("/tmp/demo-home"))
    # now `token-finops report` (in a fresh process, or with adapters
    # re-imported) reads entirely synthetic data.

`token-finops synth --out DIR [--print-env]` is the CLI wrapper.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

ALL_TOOLS = (
    "copilot", "claude_code", "codex", "gemini_cli", "hermes",
    "opencode", "cline", "aider", "continue",
)


def _copilot(out_dir: str, days: int, seed: int, scenario: str, now: datetime) -> dict:
    from .. import adapters  # noqa: F401  (side-effect import order; harmless)
    from ..adapters.copilot import build_synthetic_db

    path = os.path.join(out_dir, ".copilot", "session-store.db")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = build_synthetic_db(path, days=days, seed=seed, scenario=scenario, now=now)
    return {"path": path, "events": n, "notes": ["session-store.db, table assistant_usage_events"]}


def _claude_code(out_dir: str, days: int, seed: int, scenario: str, now: datetime) -> dict:
    from ..adapters.claude_code import build_synthetic_claude_code

    config_dir = os.path.join(out_dir, ".claude")
    result = build_synthetic_claude_code(config_dir, days=days, seed=seed, scenario=scenario, now=now)
    return {
        "path": os.path.join(config_dir, "projects"),
        "events": result["main_calls"] + result["sub_calls"],
        "notes": [
            f"main loop calls: {result['main_calls']}, sub-agent calls: {result['sub_calls']}",
            f"quota snapshot written: {result['quota_written']}",
        ],
    }


def _codex(out_dir: str, days: int, seed: int, scenario: str, now: datetime) -> dict:
    from ..adapters.codex import build_synthetic_codex

    root = os.path.join(out_dir, ".codex")
    n = build_synthetic_codex(root, days=days, seed=seed, scenario=scenario, now=now)
    return {"path": os.path.join(root, "sessions"), "events": n,
            "notes": ["rollout-*.jsonl with token_count deltas + rate_limits.primary/secondary"]}


def _gemini_cli(out_dir: str, days: int, seed: int, scenario: str, now: datetime) -> dict:
    from ..adapters.gemini_cli import build_synthetic_gemini

    root = os.path.join(out_dir, ".gemini")
    n = build_synthetic_gemini(root, days=days, seed=seed, scenario=scenario, now=now)
    return {"path": os.path.join(root, "tmp"), "events": n, "notes": ["chats/*.jsonl + projects.json"]}


def _hermes(out_dir: str, days: int, seed: int, scenario: str, now: datetime) -> dict:
    from ..adapters.hermes import build_synthetic_hermes

    root = os.path.join(out_dir, ".hermes")
    sessions = max(4, days)
    n = build_synthetic_hermes(root, sessions=sessions, seed=seed, scenario=scenario, now=now)
    return {"path": os.path.join(root, "state.db"), "events": n, "notes": ["sessions + session_model_usage"]}


def _opencode(out_dir: str, days: int, seed: int, scenario: str, now: datetime) -> dict:
    from ..adapters.opencode import build_synthetic_opencode

    path = os.path.join(out_dir, ".local", "share", "opencode", "opencode.db")
    sessions = max(3, days // 2)
    n = build_synthetic_opencode(path, sessions=sessions, seed=seed, scenario=scenario, now=now)
    return {"path": path, "events": n, "notes": ["session + session_message"]}


def _cline(out_dir: str, days: int, seed: int, scenario: str, now: datetime) -> dict:
    from ..adapters.cline import build_synthetic_cline

    root = os.path.join(out_dir, ".config", "Code", "User", "globalStorage")
    tasks = max(3, days // 2)
    n = build_synthetic_cline(root, tasks=tasks, seed=seed, scenario=scenario, now=now)
    return {"path": root, "events": n,
            "notes": ["saoudrizwan.claude-dev + rooveterinaryinc.roo-cline + kilocode.kilo-code tasks"]}


def _aider(out_dir: str, days: int, seed: int, scenario: str, now: datetime) -> dict:
    from ..adapters.aider import build_synthetic_aider

    n = build_synthetic_aider(out_dir, scenario=scenario, now=now)
    return {"path": os.path.join(out_dir, ".aider.chat.history.md"), "events": n,
            "notes": ["chat-history markdown + .aider/analytics.jsonl"]}


def _continue_dev(out_dir: str, days: int, seed: int, scenario: str, now: datetime) -> dict:
    from ..adapters.continue_dev import build_synthetic_continue

    root = os.path.join(out_dir, ".continue")
    n = build_synthetic_continue(root, scenario=scenario, now=now)
    return {"path": os.path.join(root, "sessions"), "events": n, "notes": ["sessions.json + <uuid>.json"]}


_BUILDERS = {
    "copilot": _copilot,
    "claude_code": _claude_code,
    "codex": _codex,
    "gemini_cli": _gemini_cli,
    "hermes": _hermes,
    "opencode": _opencode,
    "cline": _cline,
    "aider": _aider,
    "continue": _continue_dev,
}


def generate(out_dir: str, tools: Optional[list[str]] = None, days: int = 14,
            scenario: str = "steady", seed: int = 42,
            now: Optional[datetime] = None) -> dict:
    """Write a synthetic fake-home tree for one or more tools under `out_dir`.

    Returns a manifest: `{tool: {"path": ..., "events": ..., "notes": [...]}}`.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    os.makedirs(out_dir, exist_ok=True)

    requested = tools or list(ALL_TOOLS)
    unknown = [t for t in requested if t not in _BUILDERS]
    if unknown:
        raise ValueError(f"unknown tool(s): {', '.join(unknown)}; known: {', '.join(ALL_TOOLS)}")

    manifest: dict = {}
    for tool in requested:
        manifest[tool] = _BUILDERS[tool](out_dir, days, seed, scenario, now)
    return manifest
