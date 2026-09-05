"""Cline / Roo Code / Kilo Code (VS Code extensions) adapter.

Source: VS Code (and forks: Cursor, VSCodium) extension global storage,
`<globalStorage>/<extension-id>/tasks/<task-id>/ui_messages.json`. This is a
UI-message log, not a purpose-built telemetry store: usage data is embedded
incidentally inside `api_req_started` messages meant for rendering the chat
UI. See docs/adr/0007-cline-roo-kilo-vscode.md.

Roots probed (first existing wins nothing -- all are scanned):
- Linux:   ~/.config/Code/User/globalStorage (+ Cursor, VSCodium variants)
- macOS:   ~/Library/Application Support/Code/User/globalStorage (+ variants)
- Windows: %APPDATA%/Code/User/globalStorage (+ variants)
- `TOKEN_FINOPS_CLINE_DIRS` (colon-separated) overrides/extends the list.

Extension ids (all share the same `ui_messages.json` shape):
- `saoudrizwan.claude-dev`   -> Cline            -> tags {"extension": "cline"}
- `rooveterinaryinc.roo-cline` -> Roo Code       -> tags {"extension": "roo"}
- `kilocode.kilo-code`       -> Kilo Code        -> tags {"extension": "kilo"}

`ui_messages.json` is a JSON array of entries. Entries with
`type == "say"` and `say == "api_req_started"` carry a `text` field that is
itself a *stringified JSON* object with (field names vary slightly across
forks/versions, defensively aliased):
    {"cost": 0.0123, "tokensIn": N, "tokensOut": N,
     "cacheReads": N, "cacheWrites": N, "apiProtocol": "..."}
`ts` is epoch milliseconds.

Model resolution (best-effort, in priority order):
1. `task_metadata.json` in the same task dir: `model_usage[]` (last entry's
   `model_id`/`modelId`/`apiProvider`+`modelId`) or a top-level `modelId`.
2. `api_conversation_history.json` in the same task dir: scan for a
   `<model>...</model>`-style tag or an object with a `model` field.
3. `"unknown"`.

One `UsageEvent` per `api_req_started` entry. `session_id` = the task
directory name (`taskId`). `usd_estimate` = the embedded `cost` when present
and non-null, else `core.pricing.estimate_usd(...)`; `is_local_model` via
`core.pricing.is_local_model`. Dedup key: `(extension_id, task_id, ts_ms,
index-in-file)` -- entries carry no other stable id.

Also (best-effort, optional): the standalone Cline CLI's
`~/.cline/**/messages.json`, whose entries may carry a `metrics` object
directly (`{tokensIn, tokensOut, cacheReads, cacheWrites, cost}`) instead of
a stringified `api_req_started` payload.

Budget: BYO-key tools, no vendor-side quota concept -> `Unit.USD`,
`CycleKind.SLIDING_FROM_FIRST_USE` (30d), `allowance=None`.
"""
from __future__ import annotations

import glob
import json
import os
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Unit, UsageEvent
from ..core.pricing import estimate_usd, is_local_model
from .base import BaseAdapter, register

EXTENSION_TAGS = {
    "saoudrizwan.claude-dev": "cline",
    "rooveterinaryinc.roo-cline": "roo",
    "kilocode.kilo-code": "kilo",
}

_HOST_APPS = ("Code", "Code - Insiders", "Cursor", "VSCodium")


def _default_roots() -> list[str]:
    env = os.environ.get("TOKEN_FINOPS_CLINE_DIRS")
    if env:
        return [p for p in env.split(":") if p]

    roots: list[str] = []
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")

    for app in _HOST_APPS:
        # Linux
        roots.append(os.path.join(home, ".config", app, "User", "globalStorage"))
        # macOS
        roots.append(os.path.join(home, "Library", "Application Support", app, "User", "globalStorage"))
        # Windows
        if appdata:
            roots.append(os.path.join(appdata, app, "User", "globalStorage"))
    return roots


def _parse_ts_ms(v) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(float(v) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _num(d: dict, *keys: str) -> float:
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _model_from_task_metadata(task_dir: str) -> Optional[str]:
    path = os.path.join(task_dir, "task_metadata.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    usage = data.get("model_usage")
    if isinstance(usage, list) and usage:
        last = usage[-1]
        if isinstance(last, dict):
            m = last.get("model_id") or last.get("modelId")
            if m:
                return str(m)
    m = data.get("modelId") or data.get("model_id")
    if m:
        return str(m)
    return None


_MODEL_TAG_RE = re.compile(r"<model>\s*([^<\s][^<]*?)\s*</model>", re.IGNORECASE)


def _model_from_conversation_history(task_dir: str) -> Optional[str]:
    path = os.path.join(task_dir, "api_conversation_history.json")
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return None
    m = _MODEL_TAG_RE.search(raw)
    if m:
        return m.group(1).strip()
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    entries = data if isinstance(data, list) else data.get("messages", []) if isinstance(data, dict) else []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("model"):
            return str(entry["model"])
    return None


def _resolve_model(task_dir: str) -> str:
    return (
        _model_from_task_metadata(task_dir)
        or _model_from_conversation_history(task_dir)
        or "unknown"
    )


def _parse_task_dir(task_dir: str, extension_id: str, since: Optional[datetime]) -> Iterable[UsageEvent]:
    ui_path = os.path.join(task_dir, "ui_messages.json")
    try:
        with open(ui_path, encoding="utf-8") as fh:
            entries = json.load(fh)
    except (OSError, ValueError):
        return
    if not isinstance(entries, list):
        return

    task_id = os.path.basename(task_dir.rstrip(os.sep))
    ext_tag = EXTENSION_TAGS.get(extension_id, extension_id)
    model = None  # resolved lazily, once, only if we find a usable entry

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "say" or entry.get("say") != "api_req_started":
            continue
        text = entry.get("text")
        if not isinstance(text, str):
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue

        ts = _parse_ts_ms(entry.get("ts"))
        if ts is None:
            continue
        if since is not None and ts < since:
            continue

        tokens_in = int(_num(payload, "tokensIn"))
        tokens_out = int(_num(payload, "tokensOut"))
        cache_reads = int(_num(payload, "cacheReads"))
        cache_writes = int(_num(payload, "cacheWrites"))
        cost = payload.get("cost")

        if model is None:
            model = _resolve_model(task_dir)

        local = is_local_model(model)
        usd = None
        if not local:
            try:
                usd = float(cost) if cost is not None else None
            except (TypeError, ValueError):
                usd = None
            if usd is None:
                usd = estimate_usd(model, tokens_in, tokens_out, cache_reads, cache_writes)

        yield UsageEvent(
            ts_utc=ts,
            tool="cline",
            model_raw=model,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cache_read_tokens=cache_reads,
            cache_write_tokens=cache_writes,
            session_id=task_id,
            initiator="user",
            usd_estimate=usd,
            is_local_model=local,
            event_id=f"{extension_id}:{task_id}:{entry.get('ts')}:{idx}",
            tags={"extension": ext_tag, "api_protocol": payload.get("apiProtocol", "")},
        )


def _parse_cline_cli_messages(path: str, since: Optional[datetime]) -> Iterable[UsageEvent]:
    """Best-effort parser for the standalone Cline CLI's ~/.cline messages.json,
    where entries may carry a `metrics` object directly."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    entries = data if isinstance(data, list) else data.get("messages", []) if isinstance(data, dict) else []
    if not isinstance(entries, list):
        return
    session_id = os.path.splitext(os.path.basename(os.path.dirname(path)))[0] or "cline-cli"

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        metrics = entry.get("metrics")
        if not isinstance(metrics, dict):
            continue
        ts = _parse_ts_ms(entry.get("ts")) or _parse_ts_ms(entry.get("timestamp"))
        if ts is None:
            continue
        if since is not None and ts < since:
            continue
        model = str(entry.get("model") or entry.get("modelId") or "unknown")
        tokens_in = int(_num(metrics, "tokensIn", "input_tokens"))
        tokens_out = int(_num(metrics, "tokensOut", "output_tokens"))
        cache_reads = int(_num(metrics, "cacheReads", "cache_read_tokens"))
        cache_writes = int(_num(metrics, "cacheWrites", "cache_write_tokens"))
        cost = metrics.get("cost")
        local = is_local_model(model)
        usd = None
        if not local:
            try:
                usd = float(cost) if cost is not None else None
            except (TypeError, ValueError):
                usd = None
            if usd is None:
                usd = estimate_usd(model, tokens_in, tokens_out, cache_reads, cache_writes)
        yield UsageEvent(
            ts_utc=ts,
            tool="cline",
            model_raw=model,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cache_read_tokens=cache_reads,
            cache_write_tokens=cache_writes,
            session_id=session_id,
            initiator="user",
            usd_estimate=usd,
            is_local_model=local,
            event_id=f"cline-cli:{path}:{idx}",
            tags={"extension": "cline"},
        )


@register
class ClineAdapter(BaseAdapter):
    tool = "cline"
    display_name = "Cline / Roo / Kilo (VS Code)"

    def default_root(self) -> str:
        # Multi-root adapter: `self.root` is kept for BaseAdapter compatibility
        # (points at the first candidate), real scanning uses `_roots()`.
        roots = _default_roots()
        return roots[0] if roots else "~/.config/Code/User/globalStorage"

    def _roots(self) -> list[str]:
        env = os.environ.get("TOKEN_FINOPS_CLINE_DIRS")
        if env:
            return [os.path.expanduser(p) for p in env.split(":") if p]
        return [os.path.expanduser(p) for p in _default_roots()]

    def available(self) -> bool:
        return any(os.path.exists(r) for r in self._roots())

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        for root in self._roots():
            if not os.path.exists(root):
                continue
            for extension_id in EXTENSION_TAGS:
                tasks_glob = os.path.join(root, extension_id, "tasks", "*")
                for task_dir in sorted(glob.glob(tasks_glob)):
                    if not os.path.isdir(task_dir):
                        continue
                    yield from _parse_task_dir(task_dir, extension_id, since)

        # Standalone Cline CLI, best-effort.
        cli_root = os.path.expanduser(os.environ.get("CLINE_CLI_HOME", "~/.cline"))
        if os.path.exists(cli_root):
            for path in sorted(glob.glob(os.path.join(cli_root, "**", "messages.json"), recursive=True)):
                yield from _parse_cline_cli_messages(path, since)

    def quota(self) -> Optional[QuotaSnapshot]:
        return None

    def default_policy(self, allowance: Optional[float] = None) -> BudgetPolicy:
        return BudgetPolicy(
            tool=self.tool, window_id="30d", unit=Unit.USD, cycle=CycleKind.SLIDING_FROM_FIRST_USE,
            allowance=allowance, window_length=timedelta(days=30),
            source_of_truth="local_sum",
        )


# --------------------------------------------------------------------------- #
# Synthetic fixture builder (for tests/demos)
# --------------------------------------------------------------------------- #
_MODELS = ["claude-sonnet-4-5", "gpt-4.1", "gemini-2.5-flash"]
_LOCAL_MODEL = "ollama/qwen3-235b-a22b"


def build_synthetic_cline(root_dir: str, tasks: int = 5, seed: int = 1) -> int:
    """Write a synthetic VS Code `globalStorage`-shaped tree under `root_dir`,
    with all three extension ids present. Roughly a third of tasks omit
    `cost` (forcing estimate_usd), and one task uses a local model.

    Returns the number of `api_req_started` events written.
    """
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    ext_ids = list(EXTENSION_TAGS)
    n_events = 0

    for i in range(tasks):
        ext_id = ext_ids[i % len(ext_ids)]
        task_id = f"task-{i}-{rng.randint(1000, 9999)}"
        task_dir = os.path.join(root_dir, ext_id, "tasks", task_id)
        os.makedirs(task_dir, exist_ok=True)

        is_local = (i == tasks - 1)
        model = _LOCAL_MODEL if is_local else rng.choice(_MODELS)
        omit_cost = (i % 3 == 0) and not is_local

        n_requests = rng.randint(1, 3)
        entries = []
        for r in range(n_requests):
            ts = now - timedelta(minutes=rng.randint(0, 500))
            ts_ms = int(ts.timestamp() * 1000)
            tokens_in = rng.randint(200, 4000)
            tokens_out = rng.randint(50, 1500)
            cache_reads = rng.randint(0, 500)
            cache_writes = rng.randint(0, 200)
            payload = {
                "tokensIn": tokens_in,
                "tokensOut": tokens_out,
                "cacheReads": cache_reads,
                "cacheWrites": cache_writes,
                "apiProtocol": "anthropic",
            }
            if not omit_cost:
                payload["cost"] = round((tokens_in * 3 + tokens_out * 15) / 1e6, 6)
            entries.append({
                "ts": ts_ms,
                "type": "say",
                "say": "api_req_started",
                "text": json.dumps(payload),
            })
            n_events += 1
        # a couple of non-usage entries mixed in, to exercise skipping.
        entries.append({"ts": int(now.timestamp() * 1000), "type": "say", "say": "text", "text": "hello"})

        with open(os.path.join(task_dir, "ui_messages.json"), "w", encoding="utf-8") as fh:
            json.dump(entries, fh)

        with open(os.path.join(task_dir, "task_metadata.json"), "w", encoding="utf-8") as fh:
            json.dump({"model_usage": [{"model_id": model}]}, fh)

    return n_events
