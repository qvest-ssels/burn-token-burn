"""Gemini CLI adapter.

Source: `${GEMINI_CLI_HOME:-~/.gemini}/tmp/<projectHash>/chats/**/*.jsonl`
(sub-agent transcripts live one level deeper, in
`chats/<parentSessionId>/<id>.jsonl`), plus legacy `*.json` files anywhere
under `tmp/<projectHash>/chats/` (either a bare list of messages or
`{"messages": [...]}`).

Each JSONL file's first line is session metadata (`sessionId`,
`projectHash`, ...). Message lines with `type == "gemini"` carry the model
and a `tokens` object: `{input, output, cached, thoughts, tool, total}`
(older builds use `promptTokenCount` / `candidatesTokenCount` /
`cachedContentTokenCount` / `thoughtsTokenCount` instead).

Token accounting:
- `input` **includes** `cached` -> `cache_read = cached`, `input = input - cached`.
- Gemini bills `thoughts` (extended thinking) as *output* tokens, so for
  pricing/USD purposes `output = output + thoughts`. We keep
  `output_tokens = output + thoughts` for internal consistency (so
  `total_tokens` matches what Gemini actually billed), record
  `reasoning_tokens = thoughts` with `reasoning_is_subset_of_output=False`
  (it's added on top, not carved out of output), and stash the raw split in
  `tags`: `{"thoughts": n, "tool_tokens": n}`.

Session / agent identity:
- `session_id` = the metadata line's `sessionId`, or the file stem if no
  metadata line is present (legacy `*.json`).
- `agent_id` = the parent session id when the file lives at
  `chats/<parentSessionId>/<id>.jsonl` (a sub-agent transcript), else `""`.
- `${root}/projects.json` (`{"projects": {"<abs path>": "<hash-or-slug>"}}`)
  maps a project hash back to its cwd when present; used to fill `cwd`.

Dedup key: `(session_id, message id)`, falling back to
`(session_id, timestamp, total)` when a message has no `id`.

Budget: Gemini CLI enforces a *requests-per-day* quota (free tier 1000/day,
Standard 1500/day, Enterprise 2000/day) -> `Unit.REQUESTS`,
`CycleKind.DAILY`, default `allowance=1000`.
"""
from __future__ import annotations

import glob
import json
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..core.model import BudgetPolicy, CycleKind, QuotaSnapshot, Unit, UsageEvent
from ..core.pricing import estimate_usd
from .base import BaseAdapter, register

# TODO(quota): Gemini CLI's own quota UI calls
#   POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota
# with an OAuth bearer token read from `${root}/oauth_creds.json`. This is
# reverse-engineered (undocumented, unversioned Google-internal endpoint) and
# needs a live network call + token refresh, which this read-only, offline
# adapter deliberately does not perform. `quota()` therefore always returns
# None; runway falls back to `local_sum` against `default_policy()`. Wiring
# this up would let us report the *authoritative* daily request count instead
# of estimating from local transcripts, at the cost of network access and
# OAuth token handling that don't belong in a stdlib-only, read-only adapter.


def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            dt = datetime.fromtimestamp(float(s) / 1000.0, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _int(d: dict, *keys: str) -> int:
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return 0


def _agent_id_for(path: str, root: str) -> str:
    """Sub-agent transcripts live at chats/<parentSessionId>/<id>.jsonl or
    chats/<parentSessionId>/<id>.json; top-level ones sit directly under
    chats/. Detect the extra nesting level relative to '.../chats/'."""
    parent_dir = os.path.dirname(path)
    grandparent = os.path.basename(os.path.dirname(parent_dir))
    if grandparent == "chats":
        return os.path.basename(parent_dir)
    return ""


def _load_projects_map(root: str) -> dict:
    path = os.path.join(root, "projects.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        return {}
    # {"<abs path>": "<hash>"} -> we want hash -> path
    return {v: k for k, v in projects.items() if isinstance(v, str) and isinstance(k, str)}


def _project_hash_from_path(path: str, root: str) -> str:
    rel = os.path.relpath(path, os.path.join(root, "tmp"))
    parts = rel.split(os.sep)
    return parts[0] if parts else ""


def _event_from_message(msg: dict, *, session_id: str, agent_id: str, cwd: str,
                        since: Optional[datetime]) -> Optional[UsageEvent]:
    if msg.get("type") != "gemini":
        return None
    tokens = msg.get("tokens") or {}
    model = str(msg.get("model") or "")
    raw_input = _int(tokens, "input", "promptTokenCount")
    raw_output = _int(tokens, "output", "candidatesTokenCount")
    cached = _int(tokens, "cached", "cachedContentTokenCount")
    thoughts = _int(tokens, "thoughts", "thoughtsTokenCount")
    tool_tokens = _int(tokens, "tool")

    ts = _parse_ts(msg.get("timestamp") or msg.get("ts") or "")
    if ts is None:
        ts = datetime.now(timezone.utc)
    if since is not None and ts < since:
        return None

    inp = max(raw_input - cached, 0)
    out_for_pricing = raw_output + thoughts

    total = _int(tokens, "total") or (raw_input + raw_output + thoughts)
    msg_id = msg.get("id")
    event_id = f"{session_id}:{msg_id}" if msg_id else f"{session_id}:{ts.isoformat()}:{total}"

    return UsageEvent(
        ts_utc=ts,
        tool="gemini_cli",
        model_raw=model,
        input_tokens=inp,
        output_tokens=out_for_pricing,
        cache_read_tokens=cached,
        cache_write_tokens=0,
        reasoning_tokens=thoughts,
        reasoning_is_subset_of_output=False,
        session_id=session_id,
        agent_id=agent_id,
        parent_id="",
        initiator="agent" if agent_id else "user",
        usd_estimate=estimate_usd(model, inp, out_for_pricing, cached, 0),
        cwd=cwd,
        event_id=event_id,
        tags={"thoughts": thoughts, "tool_tokens": tool_tokens},
    )


def parse_jsonl(path: str, root: str, projects_by_hash: dict,
                since: Optional[datetime] = None) -> Iterable[UsageEvent]:
    session_id = os.path.splitext(os.path.basename(path))[0]
    agent_id = _agent_id_for(path, root)
    phash = _project_hash_from_path(path, root)
    cwd = projects_by_hash.get(phash, "")

    seen: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if i == 0 and isinstance(obj, dict) and "sessionId" in obj and "type" not in obj:
                session_id = str(obj.get("sessionId") or session_id)
                continue
            if not isinstance(obj, dict):
                continue
            ev = _event_from_message(obj, session_id=session_id, agent_id=agent_id, cwd=cwd, since=since)
            if ev is None:
                continue
            if ev.event_id in seen:
                continue
            seen.add(ev.event_id)
            yield ev


def parse_legacy_json(path: str, root: str, projects_by_hash: dict,
                      since: Optional[datetime] = None) -> Iterable[UsageEvent]:
    session_id = os.path.splitext(os.path.basename(path))[0]
    agent_id = _agent_id_for(path, root)
    phash = _project_hash_from_path(path, root)
    cwd = projects_by_hash.get(phash, "")

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return

    if isinstance(data, dict):
        messages = data.get("messages") or []
        session_id = str(data.get("sessionId") or session_id)
    elif isinstance(data, list):
        messages = data
    else:
        return

    seen: set[str] = set()
    for obj in messages:
        if not isinstance(obj, dict):
            continue
        ev = _event_from_message(obj, session_id=session_id, agent_id=agent_id, cwd=cwd, since=since)
        if ev is None:
            continue
        if ev.event_id in seen:
            continue
        seen.add(ev.event_id)
        yield ev


@register
class GeminiCliAdapter(BaseAdapter):
    tool = "gemini_cli"
    display_name = "Gemini CLI"

    def default_root(self) -> str:
        return os.environ.get("GEMINI_CLI_HOME", "~/.gemini")

    def scan(self, since: Optional[datetime] = None) -> Iterable[UsageEvent]:
        if not os.path.exists(self.root):
            return
        projects_by_hash = _load_projects_map(self.root)
        pattern_jsonl = os.path.join(self.root, "tmp", "*", "chats", "**", "*.jsonl")
        pattern_json = os.path.join(self.root, "tmp", "*", "chats", "**", "*.json")
        for path in sorted(glob.glob(pattern_jsonl, recursive=True)):
            yield from parse_jsonl(path, self.root, projects_by_hash, since)
        for path in sorted(glob.glob(pattern_json, recursive=True)):
            yield from parse_legacy_json(path, self.root, projects_by_hash, since)

    def quota(self) -> Optional[QuotaSnapshot]:
        # See the module-level TODO(quota) note: retrieveUserQuota needs a
        # live OAuth-authenticated network call this offline adapter does
        # not make. Always None for now.
        return None

    def default_policy(self, allowance: Optional[float] = None) -> BudgetPolicy:
        return BudgetPolicy(
            tool=self.tool, window_id="day", unit=Unit.REQUESTS, cycle=CycleKind.DAILY,
            allowance=1000.0 if allowance is None else allowance,
            source_of_truth="local_sum",
        )


# --------------------------------------------------------------------------- #
# Synthetic fixture builder (for tests/demos)
# --------------------------------------------------------------------------- #
_MODELS = ["gemini-2.5-pro", "gemini-2.5-flash"]


def build_synthetic_gemini(root_dir: str, days: int = 3, sessions_per_day: int = 2,
                           seed: int = 1) -> int:
    """Write a synthetic `~/.gemini`-shaped tree under `root_dir`.

    Layout: `tmp/<projectHash>/chats/session-YYYY-MM-DDTHH-MM-<id8>.jsonl`
    plus one sub-agent transcript under
    `tmp/<projectHash>/chats/<parentSessionId>/<id8>.jsonl`, and a
    `projects.json` mapping the project hash back to a fake cwd.

    Returns the number of `type == "gemini"` message events written.
    """
    rng = random.Random(seed)
    project_hash = "abc123deadbeef"
    project_cwd = "/home/demo/my-project"
    chats_dir = os.path.join(root_dir, "tmp", project_hash, "chats")
    os.makedirs(chats_dir, exist_ok=True)

    with open(os.path.join(root_dir, "projects.json"), "w", encoding="utf-8") as fh:
        json.dump({"projects": {project_cwd: project_hash}}, fh)

    now = datetime.now(timezone.utc)
    n_events = 0
    parent_session_id = None

    for day_offset in range(days):
        day = now - timedelta(days=day_offset)
        for s in range(sessions_per_day):
            session_id = f"sess-{day_offset}-{s}-{rng.randint(1000, 9999)}"
            file_id = f"{rng.getrandbits(32):08x}"
            ts_label = day.strftime("%Y-%m-%dT%H-%M")
            fname = f"session-{ts_label}-{file_id}.jsonl"
            fpath = os.path.join(chats_dir, fname)
            n_events += _write_session_file(fpath, session_id, day, rng)
            if day_offset == 0 and s == 0:
                parent_session_id = session_id

    # One sub-agent transcript, nested under the first day's first session.
    if parent_session_id is not None:
        subagent_dir = os.path.join(chats_dir, parent_session_id)
        os.makedirs(subagent_dir, exist_ok=True)
        sub_id = f"{rng.getrandbits(32):08x}"
        sub_path = os.path.join(subagent_dir, f"{sub_id}.jsonl")
        sub_session_id = f"{parent_session_id}-sub"
        n_events += _write_session_file(sub_path, sub_session_id, now, rng, n_messages=2)

    return n_events


def _write_session_file(path: str, session_id: str, base_ts: datetime, rng: random.Random,
                        n_messages: int = 3) -> int:
    lines = [json.dumps({"sessionId": session_id, "projectHash": "abc123deadbeef",
                          "startTime": base_ts.isoformat()})]
    n_gemini = 0
    for i in range(n_messages):
        ts = base_ts - timedelta(minutes=rng.randint(0, 59))
        # user turn
        lines.append(json.dumps({
            "type": "user", "id": f"{session_id}-u{i}", "timestamp": ts.isoformat(),
            "text": "synthetic prompt",
        }))
        # gemini turn
        model = rng.choice(_MODELS)
        raw_input = rng.randint(500, 5000)
        cached = rng.randint(0, min(200, raw_input))
        output = rng.randint(100, 2000)
        thoughts = rng.randint(0, 500)
        tool_tokens = rng.randint(0, 100)
        total = raw_input + output + thoughts
        lines.append(json.dumps({
            "type": "gemini", "id": f"{session_id}-g{i}", "timestamp": ts.isoformat(),
            "model": model,
            "tokens": {
                "input": raw_input, "output": output, "cached": cached,
                "thoughts": thoughts, "tool": tool_tokens, "total": total,
            },
        }))
        n_gemini += 1
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return n_gemini
