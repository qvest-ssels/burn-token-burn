"""Per-tool adapters. Each adapter is read-only and exposes:

    class XAdapter(BaseAdapter):
        tool = "x"
        def available(self) -> bool
        def scan(self, since=None) -> Iterable[UsageEvent]
        def quota(self) -> Optional[QuotaSnapshot]
        def default_policy(self, allowance=None) -> BudgetPolicy

Adapters must never write to the tool's own data store. SQLite sources are
opened with `immutable=1` (no WAL/lock interaction with the live app).
"""
from __future__ import annotations

from .base import BaseAdapter, registry, sqlite_readonly  # noqa: F401


def all_adapters() -> list[BaseAdapter]:
    # Import side effects register the adapters.
    from . import aider, claude_code, cline, codex, continue_dev, copilot, gemini_cli, hermes, opencode  # noqa: F401

    return [cls() for cls in registry.values()]
