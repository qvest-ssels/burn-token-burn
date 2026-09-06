"""Continue.dev adapter.

Source: `${CONTINUE_GLOBAL_DIR:-~/.continue}/sessions/`, an index
`sessions.json` (list of `{sessionId, title, dateCreated,
workspaceDirectory}`) plus one `<sessionId>.json` per session holding a
`history` array of chat turns.

Per ADR-0010 this field is documented as **instable**: field names and
shapes have varied across Continue versions and there is no schema
contract. This adapter is therefore deliberately tolerant: it emits one
`UsageEvent` per `history` item that carries *any* recognisable token
numbers, under whichever alias is present --

- `promptTokens` / `completionTokens` directly on the item, or
- `usage.{input_tokens, output_tokens}` / `usage.{prompt_tokens,
  completion_tokens}` nested under it,

and reads the model from `modelTitle` / `chatModelTitle` / `model`
(checked on the item, falling back to the session index entry). A history
item with no token numbers under any alias is silently skipped -- this is
expected and not an error, since assistant turns without usage information
are common depending on Continue version and provider.

Timestamps come from the item's own `timestamp` / `dateCreated` when
present (epoch ms or ISO), else the session's `dateCreated` from
`sessions.json`. Every event is tagged `{"confidence": "low"}` to flag the
field's instability to downstream reporting.

No runway: `Unit.USD`, `CycleKind.SLIDING_FROM_FIRST_USE` 30d,
`allowance=None` passthrough (BYO key, no vendor-side budget).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Unit, UsageEvent
from ..core.pricing import estimate_usd
from .base import BaseAdapter, register


def _parse_ts(v) -> Optional[datetime]:
    if v is None:
        return None
    try:
        f = float(v)
        # Heuristic: Continue writes millisecond epoch timestamps.
        if f > 1e12:
            f /= 1000.0
        return datetime.fromtimestamp(f, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        pass
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _first_int(*vals) -> Optional[int]:
    for v in vals:
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _extract_tokens(item: dict) -> tuple[Optional[int], Optional[int]]:
    usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
    inp = _first_int(
        item.get("promptTokens"),
        usage.get("input_tokens"),
        usage.get("prompt_tokens"),
    )
    out = _first_int(
        item.get("completionTokens"),
        usage.get("output_tokens"),
        usage.get("completion_tokens"),
    )
    return inp, out


def _extract_model(item: dict, session_meta: dict) -> str:
    for src in (item, session_meta):
        for key in ("modelTitle", "chatModelTitle", "model"):
            v = src.get(key)
            if v:
                return str(v)
    return ""


def _load_index(sessions_dir: str) -> dict:
    """sessionId -> index-entry dict (title, dateCreated, workspaceDirectory)."""
    path = os.path.join(sessions_dir, "sessions.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, list):
        return {}
    out = {}
    for entry in data:
        if isinstance(entry, dict) and entry.get("sessionId"):
            out[str(entry["sessionId"])] = entry
    return out


def parse_session_file(path: str, index: dict, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
    session_id = os.path.splitext(os.path.basename(path))[0]
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return

    session_meta = index.get(session_id, {})
    workspace = session_meta.get("workspaceDirectory") or ""
    session_ts_fallback = _parse_ts(session_meta.get("dateCreated")) or _parse_ts(data.get("dateCreated"))

    history = data.get("history")
    if not isinstance(history, list):
        return

    for i, item in enumerate(history):
        if not isinstance(item, dict):
            continue
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        role = message.get("role") or item.get("role")
        if role not in (None, "assistant"):
            continue

        inp, out = _extract_tokens(item)
        if inp is None and out is None:
            continue

        ts = (
            _parse_ts(item.get("timestamp"))
            or _parse_ts(item.get("dateCreated"))
            or session_ts_fallback
            or datetime.now(timezone.utc)
        )
        if since is not None and ts < since:
            continue

        model = _extract_model(item, session_meta)
        inp = inp or 0
        out = out or 0

        yield UsageEvent(
            ts_utc=ts,
            tool="continue",
            model_raw=model,
            input_tokens=inp,
            output_tokens=out,
            session_id=session_id,
            initiator="user",
            usd_estimate=estimate_usd(model, inp, out),
            cwd=str(workspace),
            event_id=f"{session_id}:{i}",
            tags={"confidence": "low"},
        )


@register
class ContinueAdapter(BaseAdapter):
    tool = "continue"
    display_name = "Continue.dev"

    def default_root(self) -> str:
        return os.environ.get("CONTINUE_GLOBAL_DIR", "~/.continue")

    @property
    def sessions_dir(self) -> str:
        return os.path.join(self.root, "sessions")

    def available(self) -> bool:
        return os.path.isdir(self.sessions_dir)

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        sessions_dir = self.sessions_dir
        if not os.path.isdir(sessions_dir):
            return
        index = _load_index(sessions_dir)
        for name in sorted(os.listdir(sessions_dir)):
            if name == "sessions.json" or not name.endswith(".json"):
                continue
            path = os.path.join(sessions_dir, name)
            yield from parse_session_file(path, index, since)

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
def build_synthetic_continue(root_dir: str, scenario: str = "steady",
                             now: Optional[datetime] = None) -> int:
    """Write a synthetic `~/.continue/sessions/`-shaped tree under
    `root_dir`: one `sessions.json` index plus two session files, one using
    the `promptTokens`/`completionTokens` alias and one using nested
    `usage.input_tokens`/`usage.output_tokens`.

    `scenario` is accepted for interface parity with the other
    build_synthetic_* generators but does not change the fixed 2-session
    output (Continue's own event count is too small for a burn profile to be
    meaningful).

    Returns the number of usage events represented.
    """
    sessions_dir = os.path.join(root_dir, "sessions")
    os.makedirs(sessions_dir, exist_ok=True)

    now = now or datetime.now(timezone.utc)
    session_a = "aaaa1111-0000-0000-0000-000000000001"
    session_b = "bbbb2222-0000-0000-0000-000000000002"

    index = [
        {
            "sessionId": session_a,
            "title": "Fix bug",
            "dateCreated": now.isoformat(),
            "workspaceDirectory": "/home/demo/proj-a",
        },
        {
            "sessionId": session_b,
            "title": "Add feature",
            "dateCreated": now.isoformat(),
            "workspaceDirectory": "/home/demo/proj-b",
        },
    ]
    with open(os.path.join(sessions_dir, "sessions.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh)

    session_a_data = {
        "sessionId": session_a,
        "history": [
            {"message": {"role": "user"}, "content": "fix this"},
            {
                "message": {"role": "assistant"},
                "modelTitle": "gpt-4.1",
                "promptTokens": 500,
                "completionTokens": 120,
                "timestamp": int(now.timestamp() * 1000),
            },
            {
                "message": {"role": "assistant"},
                "modelTitle": "gpt-4.1",
                "content": "no usage info here",
            },
        ],
    }
    with open(os.path.join(sessions_dir, f"{session_a}.json"), "w", encoding="utf-8") as fh:
        json.dump(session_a_data, fh)

    session_b_data = {
        "sessionId": session_b,
        "history": [
            {"message": {"role": "user"}, "content": "add feature"},
            {
                "message": {"role": "assistant"},
                "chatModelTitle": "claude-sonnet-4-5",
                "usage": {"input_tokens": 1000, "output_tokens": 300},
                "timestamp": now.isoformat(),
            },
        ],
    }
    with open(os.path.join(sessions_dir, f"{session_b}.json"), "w", encoding="utf-8") as fh:
        json.dump(session_b_data, fh)

    return 2
