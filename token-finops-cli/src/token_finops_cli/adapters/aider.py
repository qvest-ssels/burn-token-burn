"""Aider adapter.

Two sources, in order of preference:

1. Opt-in structured analytics JSONL (`--analytics-log`): env
   `TOKEN_FINOPS_AIDER_ANALYTICS`, else `~/.aider/analytics.jsonl` when it
   exists. Lines are JSON objects; only `event == "message_send"" rows carry
   usage, with `properties.{prompt_tokens, completion_tokens, cost,
   main_model, time}`. This is the reliable path (ADR-0009) and is always
   read when present, in addition to the chat-history scrape below.

2. The default, more fragile path: `.aider.chat.history.md` files, Aider's
   running Markdown chat log written per working directory. Search roots come
   from env `TOKEN_FINOPS_AIDER_DIRS` (colon-separated), defaulting to `~`,
   walked shallowly (max depth 3, hidden directories skipped except for the
   history file itself, `node_modules`/`.venv` skipped). Each file is parsed
   as a sequence of blocks:

   - `# aider chat started at 2026-09-01 10:00:00` opens a new block and
     supplies the timestamp used for every event in that block -- Aider does
     not stamp individual turns, so every event derived from a block is
     tagged `{"ts_approx": True}`.
   - `> Model: <name> with ...` sets the model in effect for subsequent usage
     lines in the block.
   - `> Tokens: 3,052 sent, 502 received. Cost: $0.02 message, $0.02 session.`
     (and the `12k sent, 1.5k received` / `$0.0123 message` variants) is a
     usage line: sent -> input, received -> output, and the *message* cost
     (not the cumulative session cost) is used as `usd_estimate` when
     present, falling back to `core.pricing.estimate_usd` otherwise.

   `session_id` = `"<file path>:<chat-start timestamp>"` so that two chat
   blocks in the same file (Aider appends, never truncates) get distinct
   session ids. Nothing is deduplicated beyond that -- the log is
   append-only and each usage line is a distinct turn.

No runway: `Unit.USD`, `CycleKind.SLIDING_FROM_FIRST_USE` 30d,
`allowance=None` passthrough (BYO key, no vendor-side budget).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Unit, UsageEvent
from ..core.pricing import estimate_usd
from .base import BaseAdapter, register

_SKIP_DIRS = {"node_modules", ".venv", "venv", ".git", "__pycache__"}
_HISTORY_NAME = ".aider.chat.history.md"

_CHAT_START_RE = re.compile(r"^#\s*aider chat started at\s+([0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9:]{5,8})")
_MODEL_RE = re.compile(r"^>\s*Model:\s*(\S+)")
_TOKENS_RE = re.compile(
    r"^>\s*Tokens:\s*([0-9.,]+k?)\s*sent,\s*([0-9.,]+k?)\s*received\.?"
    r"(?:\s*Cost:\s*\$([0-9.]+)\s*message(?:,\s*\$([0-9.]+)\s*session)?\.?)?",
    re.IGNORECASE,
)


def _parse_number(s: str) -> float:
    """'3,052' -> 3052.0; '12k' -> 12000.0; '1.5k' -> 1500.0."""
    s = s.strip().replace(",", "")
    if s.lower().endswith("k"):
        return float(s[:-1]) * 1000.0
    return float(s)


def _parse_chat_start(s: str) -> Optional[datetime]:
    s = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=timezone.utc)
    return None


def _iter_history_paths(search_roots: list[str]) -> Iterable[str]:
    for root in search_roots:
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
            if depth >= 3:
                dirnames[:] = []
            dirnames[:] = [
                d for d in dirnames
                if d not in _SKIP_DIRS and not d.startswith(".")
            ]
            if _HISTORY_NAME in filenames:
                yield os.path.join(dirpath, _HISTORY_NAME)


def _search_roots() -> list[str]:
    env = os.environ.get("TOKEN_FINOPS_AIDER_DIRS")
    if env:
        return [p for p in env.split(":") if p]
    return ["~"]


def parse_history_file(path: str, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return

    block_start: Optional[datetime] = None
    model = ""

    for line in lines:
        line = line.rstrip("\n")

        m = _CHAT_START_RE.match(line)
        if m:
            block_start = _parse_chat_start(m.group(1))
            model = ""
            continue

        m = _MODEL_RE.match(line)
        if m:
            model = m.group(1)
            continue

        m = _TOKENS_RE.match(line)
        if not m:
            continue
        if block_start is None:
            # Usage line with no preceding "chat started at" header -- use
            # file mtime as a last-resort timestamp so the event isn't lost.
            try:
                block_start = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
            except OSError:
                block_start = datetime.now(timezone.utc)

        if since is not None and block_start < since:
            continue

        try:
            sent = _parse_number(m.group(1))
            received = _parse_number(m.group(2))
        except ValueError:
            continue
        message_cost = m.group(3)
        usd = float(message_cost) if message_cost is not None else estimate_usd(
            model, int(sent), int(received)
        )

        session_id = f"{path}:{block_start.isoformat()}"
        yield UsageEvent(
            ts_utc=block_start,
            tool="aider",
            model_raw=model,
            input_tokens=int(sent),
            output_tokens=int(received),
            session_id=session_id,
            initiator="user",
            usd_estimate=usd,
            cwd=os.path.dirname(path),
            event_id=f"{session_id}:{sent}:{received}",
            tags={"ts_approx": True},
        )


def parse_analytics_jsonl(path: str, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict) or obj.get("event") != "message_send":
                continue
            props = obj.get("properties") or {}
            if not isinstance(props, dict):
                continue

            ts = None
            t = props.get("time") or obj.get("time")
            if t is not None:
                try:
                    ts = datetime.fromtimestamp(float(t), tz=timezone.utc)
                except (TypeError, ValueError, OSError):
                    try:
                        ts = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        ts = ts.astimezone(timezone.utc)
                    except (TypeError, ValueError):
                        ts = None
            if ts is None:
                ts = datetime.now(timezone.utc)
            if since is not None and ts < since:
                continue

            prompt_tokens = props.get("prompt_tokens")
            completion_tokens = props.get("completion_tokens")
            if prompt_tokens is None and completion_tokens is None:
                continue
            model = str(props.get("main_model") or "")
            cost = props.get("cost")
            inp = int(prompt_tokens or 0)
            out = int(completion_tokens or 0)
            usd = float(cost) if cost is not None else estimate_usd(model, inp, out)

            yield UsageEvent(
                ts_utc=ts,
                tool="aider",
                model_raw=model,
                input_tokens=inp,
                output_tokens=out,
                session_id=f"{path}:analytics",
                initiator="user",
                usd_estimate=usd,
                event_id=f"{path}:{i}",
                tags={},
            )


@register
class AiderAdapter(BaseAdapter):
    tool = "aider"
    display_name = "Aider"

    def default_root(self) -> str:
        # There is no single root for Aider -- chat history lives per
        # working directory. `root` is kept for BaseAdapter compatibility
        # (used by `available()`) and points at the first configured/default
        # search root.
        return _search_roots()[0]

    def available(self) -> bool:
        if any(os.path.isdir(os.path.expanduser(r)) for r in _search_roots()):
            return True
        return os.path.exists(self._analytics_path())

    def _analytics_path(self) -> str:
        return os.path.expanduser(
            os.environ.get("TOKEN_FINOPS_AIDER_ANALYTICS", "~/.aider/analytics.jsonl")
        )

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        for path in _iter_history_paths(_search_roots()):
            yield from parse_history_file(path, since)

        analytics_path = self._analytics_path()
        if os.path.exists(analytics_path):
            yield from parse_analytics_jsonl(analytics_path, since)

    def quota(self) -> Optional[QuotaSnapshot]:
        return None

    def default_policy(self, allowance: Optional[float] = None) -> BudgetPolicy:
        return BudgetPolicy(
            tool=self.tool, window_id="30d", unit=Unit.USD,
            cycle=CycleKind.SLIDING_FROM_FIRST_USE,
            window_length=timedelta(days=30),
            allowance=allowance,
            source_of_truth="local_sum",
        )


# --------------------------------------------------------------------------- #
# Synthetic fixture builder (for tests/demos)
# --------------------------------------------------------------------------- #
def build_synthetic_aider(root_dir: str, scenario: str = "steady",
                          now: Optional[datetime] = None) -> int:
    """Write one `.aider.chat.history.md` (two chat blocks, one number-format
    each) plus one `analytics.jsonl` (one `message_send` row) under
    `root_dir`.

    `scenario` shifts the two chat-block timestamps to "yesterday" and
    "today" (relative to `now`) instead of a fixed 2026-09 date, and (for
    "quiet") widens the gap between them; it does not change the token/cost
    figures. "steady" (the default) reproduces the exact pre-scenario output.

    Returns the total number of usage events represented across both
    sources.
    """
    os.makedirs(root_dir, exist_ok=True)
    history_path = os.path.join(root_dir, _HISTORY_NAME)
    if scenario == "steady":
        ts_a, ts_b = "2026-09-01 10:00:00", "2026-09-02 11:30:00"
        analytics_time = datetime.now(timezone.utc).timestamp()
    else:
        base = now or datetime.now(timezone.utc)
        gap_days = 7 if scenario == "quiet" else 1
        ts_a = (base - timedelta(days=gap_days, hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        ts_b = (base - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        analytics_time = base.timestamp()
    with open(history_path, "w", encoding="utf-8") as fh:
        fh.write(
            f"# aider chat started at {ts_a}\n\n"
            "> Model: gpt-4.1 with diff edit format\n\n"
            "#### add a test\n\n"
            "> Tokens: 3,052 sent, 502 received. Cost: $0.02 message, $0.02 session.\n\n"
            f"# aider chat started at {ts_b}\n\n"
            "> Model: gpt-4.1 with diff edit format\n\n"
            "#### refactor\n\n"
            "> Tokens: 12k sent, 1.5k received. Cost: $0.15 message, $0.15 session.\n\n"
        )

    analytics_dir = os.path.join(root_dir, ".aider")
    os.makedirs(analytics_dir, exist_ok=True)
    analytics_path = os.path.join(analytics_dir, "analytics.jsonl")
    with open(analytics_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "event": "message_send",
            "properties": {
                "prompt_tokens": 800,
                "completion_tokens": 200,
                "cost": 0.01,
                "main_model": "gpt-4.1",
                "time": analytics_time,
            },
        }) + "\n")

    return 3
