from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Iterable, Optional

from ..core.model import BudgetPolicy, QuotaSnapshot, UsageEvent

registry: dict[str, type["BaseAdapter"]] = {}


def register(cls):
    registry[cls.tool] = cls
    return cls


def sqlite_readonly(path: str) -> sqlite3.Connection:
    """Open a SQLite file strictly read-only and without touching its WAL/lock
    files. `immutable=1` tells SQLite the file cannot change underneath us, so
    it never takes a shared lock — safe next to a live app (the original
    token-finops-cli used `mode=ro`, which still locks)."""
    uri = f"file:{os.path.abspath(path)}?immutable=1"
    return sqlite3.connect(uri, uri=True)


class BaseAdapter:
    tool: str = "base"
    display_name: str = "Base"

    def __init__(self, root: Optional[str] = None):
        self.root = os.path.expanduser(root or self.default_root())

    def default_root(self) -> str:
        raise NotImplementedError

    def available(self) -> bool:
        return os.path.exists(self.root)

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        raise NotImplementedError

    def quota(self) -> Optional[QuotaSnapshot]:
        return None

    def default_policy(self, allowance: Optional[float] = None) -> BudgetPolicy:
        raise NotImplementedError

    # convenience
    def events(self, since: Optional[datetime] = None) -> list[UsageEvent]:
        evs = list(self.scan(since))
        evs.sort(key=lambda e: e.ts_utc)
        return evs
