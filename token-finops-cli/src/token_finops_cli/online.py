"""Optional live quota fetchers (`--online`) — never on by default.

Everything in this module is opt-in. `report`/`status` only call
`online_quota()` when the user passed `--online`; without the flag not a
single byte leaves the machine and the tool behaves exactly as it always
did (AGENTS.md: "Do not add network calls without an explicit `--online`
flag and an ADR note; default runs must work offline").

Four endpoints, one per tool (see `docs/sources.md` and ADRs 0001/0002/0004/0005):

| tool          | request                                                        | documented? |
|---------------|----------------------------------------------------------------|-------------|
| `copilot`     | `GET  api.github.com/copilot_internal/user`                     | RE, self-used by the Copilot CLI |
| `claude_code` | `GET  api.anthropic.com/api/oauth/usage`                        | RE, heavily 429-rate-limited |
| `gemini_cli`  | `POST cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota` | RE, Google-internal |
| `hermes`      | `GET  openrouter.ai/api/v1/key`                                 | **official** OpenRouter API |

Three of the four are reverse-engineered, unversioned and may break without
notice. That is precisely why this path is opt-in and why every failure mode
is treated the same way:

**Hard-fail closed.** No network, no credentials, a timeout, an HTTP error, a
429, a non-JSON body, a JSON body in an unexpected shape, a clock that cannot
parse a reset timestamp — all of it returns `None`, and the caller keeps the
offline `QuotaSnapshot` it already had. Running `--online` on a laptop in
flight mode prints exactly what running without the flag prints: no
traceback, no error line, no half-applied quota. `online_quota()` is wrapped
in a blanket `except Exception` for that reason; a fetcher that raises
something unforeseen must not take out the user's status bar.

**Cached >= 180 s** in `~/.token-finops/online-cache.json` (override with
`$TOKEN_FINOPS_ONLINE_CACHE`). `status` is polled every few seconds by tmux /
waybar / starship, and three of these endpoints are undocumented and
rate-limited — an uncached fetcher would get the user 429'd within a minute.
Failures are cached too (as a negative entry), so a machine with no
credentials retries at most once every 180 s instead of on every prompt
redraw. That cache is *this tool's own* data, next to the `quota.json` the
status-line collector already writes; the "never write to another tool's
store" rule (`~/.copilot`, `~/.claude`, ...) is untouched.

**Credentials are read, never written.** `gh auth token` / `$GITHUB_TOKEN`,
`~/.claude/.credentials.json`, `~/.gemini/oauth_creds.json` and
`$OPENROUTER_API_KEY` are read to build an `Authorization` header and nothing
else. No token is refreshed, rewritten, logged or put in the cache file (the
cache holds only the parsed response). An expired OAuth token therefore just
fails closed like any other error — this module will not re-authenticate on
the user's behalf.

stdlib only: `urllib.request` / `urllib.error`, no `requests`/`httpx`.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from .core.model import QuotaSnapshot

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
CACHE_ENV = "TOKEN_FINOPS_ONLINE_CACHE"
DEFAULT_CACHE_PATH = "~/.token-finops/online-cache.json"
CACHE_TTL_SECONDS = 180.0          # T-03 floor; the endpoints are rate-limited
HTTP_TIMEOUT_SECONDS = 6.0
USER_AGENT = "token-finops (+https://github.com/tronicum/burn-token-burn)"

COPILOT_URL = "https://api.github.com/copilot_internal/user"
ANTHROPIC_URL = "https://api.anthropic.com/api/oauth/usage"
ANTHROPIC_BETA = "oauth-2025-04-20"
GEMINI_URL = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota"
OPENROUTER_URL = "https://openrouter.ai/api/v1/key"


def cache_path() -> str:
    """Resolved lazily (not at import time) so a test's temporary HOME — and
    `$TOKEN_FINOPS_ONLINE_CACHE` — are honoured."""
    return os.path.expanduser(os.environ.get(CACHE_ENV) or DEFAULT_CACHE_PATH)


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
def _load_cache() -> dict:
    """The whole cache file, or `{}`. Missing, unreadable, corrupt or
    wrong-shaped is a cache *miss*, never an error."""
    try:
        with open(cache_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def cache_get(key: str, now: Optional[float] = None) -> Optional[dict]:
    """The cached entry for `key` if it is younger than `CACHE_TTL_SECONDS`.

    Returns the entry itself (`{"fetched_at": ..., "payload": ...}`); a
    negative entry has `payload` set to `None` and still counts as a hit, so a
    machine without credentials does not retry on every statusline redraw."""
    entry = _load_cache().get(key)
    if not isinstance(entry, dict):
        return None
    try:
        age = (time.time() if now is None else now) - float(entry.get("fetched_at"))
    except (TypeError, ValueError):
        return None
    if age < 0 or age >= CACHE_TTL_SECONDS:   # a future timestamp is also a miss
        return None
    return entry


def cache_put(key: str, payload: Optional[dict], now: Optional[float] = None) -> None:
    """Store a response (or `None` for "this failed") under `key`. Best-effort:
    an unwritable cache directory means the next run simply fetches again."""
    data = _load_cache()
    data[key] = {"fetched_at": time.time() if now is None else now, "payload": payload}
    path = cache_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        return


# --------------------------------------------------------------------------- #
# HTTP (stdlib only)
# --------------------------------------------------------------------------- #
def http_json(url: str, *, headers: Optional[dict] = None, method: str = "GET",
              body: Optional[bytes] = None) -> Optional[dict]:
    """One request, one parsed JSON object, or `None`.

    Every failure mode collapses to `None`: DNS/connection errors, timeouts,
    any non-2xx status (including the 429 the Anthropic endpoint hands out
    freely), a body that is not JSON, and a body that is JSON but not an
    object."""
    hdrs = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- #
# Credentials — read-only, never written or refreshed
# --------------------------------------------------------------------------- #
def _read_json_file(path: str) -> Optional[dict]:
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _deep_find(data: Any, keys: tuple[str, ...], depth: int = 6) -> Optional[str]:
    """First non-empty string stored under any of `keys`, searched breadth-first.

    Credential files nest differently across versions (`{"claudeAiOauth":
    {"accessToken": ...}}` vs a flat `{"access_token": ...}`); a shape-tolerant
    lookup beats a hardcoded path that breaks on the next release."""
    if depth < 0:
        return None
    if isinstance(data, dict):
        for key in keys:
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        for val in data.values():
            found = _deep_find(val, keys, depth - 1)
            if found:
                return found
    elif isinstance(data, list):
        for val in data:
            found = _deep_find(val, keys, depth - 1)
            if found:
                return found
    return None


def github_token() -> Optional[str]:
    """`$GITHUB_TOKEN`/`$GH_TOKEN`, else whatever `gh auth token` prints.

    The `gh` call is read-only (it prints the token the user already stored)
    and is skipped entirely if `gh` is not installed. Never writes, never
    triggers an interactive login (`gh auth token` fails closed when logged
    out, which lands on the same `None` as every other failure)."""
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                             timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    token = (out.stdout or "").strip()
    return token if out.returncode == 0 and token else None


def anthropic_token() -> Optional[str]:
    """OAuth access token from `~/.claude/.credentials.json` (read-only).

    Not found on macOS installs that keep the token in the Keychain — that is
    a plain cache-miss/fail-closed case, not an error; the status-line
    collector remains the supported quota source (ADR-0002)."""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"
    data = _read_json_file(os.path.join(os.path.expanduser(cfg), ".credentials.json"))
    return _deep_find(data, ("accessToken", "access_token"))


def gemini_token() -> Optional[str]:
    """OAuth access token from `${GEMINI_CLI_HOME:-~/.gemini}/oauth_creds.json`.

    Read as-is: an expired token is *not* refreshed here (that would mean
    writing to Gemini CLI's own credential store, which ground rule 1
    forbids) — it simply 401s and falls back to the offline path."""
    root = os.environ.get("GEMINI_CLI_HOME") or "~/.gemini"
    data = _read_json_file(os.path.join(os.path.expanduser(root), "oauth_creds.json"))
    return _deep_find(data, ("access_token", "accessToken"))


def openrouter_key() -> Optional[str]:
    """`$OPENROUTER_API_KEY` (or `$OPENROUTER_KEY`), else Hermes's own config.

    Hermes is bring-your-own-provider, so the key lives in the user's
    environment or in `${HERMES_HOME:-~/.hermes}/config.json`; both are read,
    neither is written."""
    for var in ("OPENROUTER_API_KEY", "OPENROUTER_KEY"):
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()
    root = os.environ.get("HERMES_HOME") or "~/.hermes"
    for name in ("config.json", "settings.json"):
        key = _deep_find(_read_json_file(os.path.join(os.path.expanduser(root), name)),
                         ("openrouter_api_key", "openrouterApiKey", "api_key", "apiKey"))
        if key:
            return key
    return None


# --------------------------------------------------------------------------- #
# Shape-tolerant parsing helpers
# --------------------------------------------------------------------------- #
def _as_float(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out or out in (float("inf"), float("-inf")) else out


def _parse_ts(value) -> Optional[datetime]:
    """ISO-8601 (with or without `Z`), epoch seconds, or epoch millis -> UTC."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        secs = float(value)
        if secs > 1e12:
            secs /= 1000.0
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _pick(data: dict, *names: str):
    """First present key out of `names` (field-alias lists, AGENTS.md #7)."""
    for name in names:
        if isinstance(data, dict) and data.get(name) is not None:
            return data[name]
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Parsers: raw response -> QuotaSnapshot (pure; no I/O, so they are cacheable)
# --------------------------------------------------------------------------- #
def parse_copilot(data: dict) -> Optional[QuotaSnapshot]:
    """`quota_snapshots.chat.percent_remaining` + `quota_reset_date`
    (ADR-0001). `percent_remaining` is what GitHub's own SDK surfaces as
    `account.getQuota`, so used = 100 - remaining."""
    if not isinstance(data, dict):
        return None
    snaps = _pick(data, "quota_snapshots", "quotaSnapshots") or {}
    chat = _pick(snaps, "chat", "premium_interactions", "completions") if isinstance(snaps, dict) else None
    if not isinstance(chat, dict):
        return None
    remaining = _as_float(_pick(chat, "percent_remaining", "percentRemaining"))
    if remaining is None:
        return None
    used_fraction = max(0.0, min(1.0, 1.0 - remaining / 100.0))
    entitlement = _as_float(_pick(chat, "entitlement", "quota"))
    left = _as_float(_pick(chat, "remaining"))
    used_units = None if entitlement is None or left is None else max(0.0, entitlement - left)
    return QuotaSnapshot(
        tool="copilot", window_id="month", observed_at=_now(), used_fraction=used_fraction,
        used_units=used_units, limit_units=entitlement,
        resets_at=_parse_ts(_pick(data, "quota_reset_date", "quota_reset_at", "quotaResetDate")),
        source="copilot_online",
    )


def parse_anthropic(data: dict, window: str = "five_hour") -> Optional[QuotaSnapshot]:
    """`five_hour`/`seven_day` utilisation from the RE `oauth/usage` endpoint.

    The response shape is undocumented and has already been observed both as
    a percentage (0-100) and as a 0-1 fraction, so a value <= 1 is read as a
    fraction and anything larger as a percentage."""
    if not isinstance(data, dict):
        return None
    aliases = {"five_hour": ("five_hour", "fiveHour", "5h"),
               "seven_day": ("seven_day", "sevenDay", "7d")}[window]
    block = _pick(data, *aliases)
    if block is None:
        nested = _pick(data, "rate_limits", "rateLimits", "usage") or {}
        block = _pick(nested, *aliases) if isinstance(nested, dict) else None
    if not isinstance(block, dict):
        return None
    raw = _as_float(_pick(block, "utilization", "used_percentage", "usedPercentage",
                          "used_fraction", "percent_used"))
    if raw is None:
        return None
    used_fraction = raw if raw <= 1.0 else raw / 100.0
    return QuotaSnapshot(
        tool="claude_code", window_id="5h" if window == "five_hour" else "7d",
        observed_at=_now(), used_fraction=max(0.0, min(1.0, used_fraction)),
        resets_at=_parse_ts(_pick(block, "resets_at", "resetsAt", "reset_time", "resetTime")),
        source="claude_oauth_usage",
    )


def parse_gemini(data: dict) -> Optional[QuotaSnapshot]:
    """`buckets[{remainingFraction, resetTime}]` (ADR-0004).

    Several buckets can be returned (per-model, per-tier); the *binding* one
    is the emptiest, so the smallest `remainingFraction` wins — same
    "binding constraint" rule the cross-tool roll-up uses."""
    if not isinstance(data, dict):
        return None
    buckets = _pick(data, "buckets", "quotaBuckets", "quota_buckets")
    if not isinstance(buckets, list):
        return None
    best: Optional[tuple[float, Any]] = None
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        remaining = _as_float(_pick(bucket, "remainingFraction", "remaining_fraction"))
        if remaining is None:
            continue
        if best is None or remaining < best[0]:
            best = (remaining, _pick(bucket, "resetTime", "reset_time", "resetsAt"))
    if best is None:
        return None
    return QuotaSnapshot(
        tool="gemini_cli", window_id="day", observed_at=_now(),
        used_fraction=max(0.0, min(1.0, 1.0 - best[0])),
        resets_at=_parse_ts(best[1]), source="gemini_online",
    )


def parse_openrouter(data: dict) -> Optional[QuotaSnapshot]:
    """`data{usage, limit, limit_remaining}` from the official key endpoint
    (ADR-0005). `limit: null` means "no credit limit on this key" — real
    usage in dollars, but no fraction to report."""
    if not isinstance(data, dict):
        return None
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    usage = _as_float(_pick(payload, "usage", "usage_daily"))
    limit = _as_float(_pick(payload, "limit"))
    remaining = _as_float(_pick(payload, "limit_remaining", "limitRemaining"))
    if usage is None and remaining is None:
        return None
    if usage is None and limit is not None and remaining is not None:
        usage = max(0.0, limit - remaining)
    used_fraction = None
    if limit and limit > 0 and usage is not None:
        used_fraction = max(0.0, min(1.0, usage / limit))
    return QuotaSnapshot(
        tool="hermes", window_id="30d", observed_at=_now(), used_fraction=used_fraction,
        used_units=usage, limit_units=limit, source="openrouter_key",
    )


# --------------------------------------------------------------------------- #
# Fetchers: credentials + HTTP + cache + parse
# --------------------------------------------------------------------------- #
def _cached_fetch(key: str, fetch) -> Optional[dict]:
    """Shared cache wrapper: a hit (positive *or* negative) short-circuits the
    request; a miss calls `fetch()` and stores whatever came back."""
    entry = cache_get(key)
    if entry is not None:
        payload = entry.get("payload")
        return payload if isinstance(payload, dict) else None
    payload = fetch()
    cache_put(key, payload if isinstance(payload, dict) else None)
    return payload if isinstance(payload, dict) else None


def fetch_copilot_online() -> Optional[QuotaSnapshot]:
    def go():
        token = github_token()
        if not token:
            return None
        return http_json(COPILOT_URL, headers={
            "Authorization": f"token {token}",
            "Editor-Version": "vscode/1.0.0",          # the endpoint 400s without one
            "Editor-Plugin-Version": "copilot/1.0.0",
        })

    return parse_copilot(_cached_fetch("copilot", go) or {})


def fetch_claude_online(window: str = "five_hour") -> Optional[QuotaSnapshot]:
    def go():
        token = anthropic_token()
        if not token:
            return None
        return http_json(ANTHROPIC_URL, headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": ANTHROPIC_BETA,
        })

    return parse_anthropic(_cached_fetch("claude_code", go) or {}, window)


def fetch_gemini_online() -> Optional[QuotaSnapshot]:
    def go():
        token = gemini_token()
        if not token:
            return None
        return http_json(GEMINI_URL, method="POST", body=b"{}", headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })

    return parse_gemini(_cached_fetch("gemini_cli", go) or {})


def fetch_openrouter_online() -> Optional[QuotaSnapshot]:
    def go():
        key = openrouter_key()
        if not key:
            return None
        return http_json(OPENROUTER_URL, headers={"Authorization": f"Bearer {key}"})

    return parse_openrouter(_cached_fetch("hermes", go) or {})


FETCHERS = {
    "copilot": fetch_copilot_online,
    "claude_code": fetch_claude_online,
    "gemini_cli": fetch_gemini_online,
    "hermes": fetch_openrouter_online,
}


def online_quota(tool: str) -> Optional[QuotaSnapshot]:
    """The live `QuotaSnapshot` for `tool`, or `None` — the single entry point
    `report`/`status` call when `--online` is set.

    The blanket `except Exception` is the fail-closed guarantee in one place:
    whatever a reverse-engineered endpoint decides to return tomorrow, the
    caller keeps its offline snapshot and the user sees an ordinary report.
    A tool with no fetcher (codex, cline, aider, ...) simply returns `None`."""
    fetcher = FETCHERS.get(tool)
    if fetcher is None:
        return None
    try:
        snap = fetcher()
    except Exception:       # noqa: BLE001 — fail closed to the offline path, always
        return None
    return snap if isinstance(snap, QuotaSnapshot) else None
