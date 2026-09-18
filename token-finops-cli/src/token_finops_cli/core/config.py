"""User configuration: `~/.token-finops/config.json` plus `TOKEN_FINOPS_*` env vars.

Everything here is *opt-in*. The config file does not exist unless the user creates
it, and every setting has the same hardcoded default it had before this module
existed, so a machine without a config file behaves exactly as it always did.

Precedence, highest first:

    explicit CLI flag  >  TOKEN_FINOPS_* env var  >  config.json  >  hardcoded default

The CLI tier is installed by `cli.main()` via `set_cli_overrides()` before any
subcommand runs, so a flag passed on the command line wins no matter how deep in
the call stack the `BudgetPolicy` is finally constructed.

Schema (every key optional)::

    {
      "default_tool": "claude_code",
      "statusline": {"show_subagents": true},
      "budget": {
        "warn_at": 0.80,
        "critical_at": 0.95,
        "cycle_day": 15,
        "allowance": {"copilot": 3000, "gemini_cli": 1000},
        "window_hours": {"claude_code:5h": 26, "codex": 30}
      }
    }

**Invalid values never abort the run.** A bad value is reported once on stderr and then
skipped: resolution carries on down the precedence chain to the next tier that has an
opinion, ending at the hardcoded default. (So a bad env var falls back to the user's
`config.json` value if there is one -- a broken setting never promotes itself past a
working one.) Rationale: `token-finops` is a read-only
observability tool that people wire into statuslines, tmux status bars and Claude
Code hooks, where it is re-executed on every prompt. A hard failure there would
take out the user's shell prompt over a typo in an optional settings file; a loud
fallback keeps the prompt alive *and* tells them what was ignored. (Nothing here
silently misbehaves -- the warning names the source, the key and the value.)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from typing import Any, Iterable, Optional

# --------------------------------------------------------------------------- #
# Names
# --------------------------------------------------------------------------- #
CONFIG_PATH_ENV = "TOKEN_FINOPS_CONFIG"
DEFAULT_CONFIG_PATH = "~/.token-finops/config.json"

ENV_WARN_AT = "TOKEN_FINOPS_WARN_AT"
ENV_CRITICAL_AT = "TOKEN_FINOPS_CRITICAL_AT"
ENV_DEFAULT_TOOL = "TOKEN_FINOPS_DEFAULT_TOOL"
ENV_CYCLE_DAY = "TOKEN_FINOPS_CYCLE_DAY"
ENV_BUDGET = "TOKEN_FINOPS_BUDGET"            # Copilot monthly AI-unit allowance (== --budget)
ENV_ALLOWANCE = "TOKEN_FINOPS_ALLOWANCE"      # allowance for every other tool (== --allowance)
ENV_WINDOW_HOURS = "TOKEN_FINOPS_WINDOW_HOURS"

# Hardcoded defaults -- the values these settings had before they were configurable.
DEFAULT_WARN_AT = 0.75
DEFAULT_CRITICAL_AT = 0.90
DEFAULT_CYCLE_DAY = 1

# Day 29-31 would make `calendar_month_window()` raise in February; a monthly cycle
# that can actually happen every month is capped at 28.
MAX_CYCLE_DAY = 28

# --------------------------------------------------------------------------- #
# Process state
# --------------------------------------------------------------------------- #
_cli: dict[str, Any] = {}
_warned: set[str] = set()


def set_cli_overrides(*, copilot_allowance: Optional[float] = None, allowance: Optional[float] = None,
                      cycle_day: Optional[int] = None) -> None:
    """Install the values an explicit CLI flag carried. `None` means "flag not passed"
    and leaves the lower tiers in charge. Replaces (never merges into) whatever a
    previous call installed, so one `main()` invocation cannot leak flags into the
    next one when the CLI is driven in-process."""
    _cli.clear()
    for key, val in (("copilot_allowance", copilot_allowance), ("allowance", allowance),
                     ("cycle_day", cycle_day)):
        if val is not None:
            _cli[key] = val


def reset() -> None:
    """Drop CLI overrides and the warn-once memory (used by the test suite)."""
    _cli.clear()
    _warned.clear()


def _warn(msg: str) -> None:
    """Report an ignored setting once per process -- `report` builds one policy per
    adapter, and nine copies of the same complaint is noise, not information."""
    if msg in _warned:
        return
    _warned.add(msg)
    print(msg, file=sys.stderr)


# --------------------------------------------------------------------------- #
# The file
# --------------------------------------------------------------------------- #
def config_path() -> str:
    return os.path.expanduser(os.environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH)


def load_config() -> dict:
    """The parsed config file, or `{}`. Never raises: a missing, unreadable, corrupt
    or non-object file is treated as "no settings", exactly like the original
    `cli._statusline_config()` this generalises."""
    try:
        with open(config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def section(name: str) -> dict:
    """One top-level object from the config file (`statusline`, `budget`, ...)."""
    val = load_config().get(name)
    return val if isinstance(val, dict) else {}


def _budget(key: str) -> Any:
    return section("budget").get(key)


# --------------------------------------------------------------------------- #
# Generic resolution
# --------------------------------------------------------------------------- #
def _sources(cli_key: Optional[str], env_name: Optional[str], cfg_value: Any,
             cfg_label: str = "", cli_flag: str = ""):
    """(label, raw) for each tier that actually carries a value, highest first. The
    label names the tier in the user's own vocabulary, so a warning says *which*
    of the four places the bad value came from."""
    out = []
    if cli_key is not None and _cli.get(cli_key) is not None:
        out.append((cli_flag or f"--{cli_key.replace('_', '-')}", _cli[cli_key]))
    if env_name and os.environ.get(env_name) not in (None, ""):
        out.append((f"${env_name}", os.environ[env_name]))
    if cfg_value is not None:
        out.append((f"config.json {cfg_label}", cfg_value))
    return out


def _as_float(label: str, key: str, raw: Any, *, lo: float, hi: float,
              lo_inclusive: bool = False) -> Optional[float]:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        _warn(f"token-finops: ignoring {label} {key}={raw!r} -- not a number")
        return None
    if val != val or val in (float("inf"), float("-inf")):
        _warn(f"token-finops: ignoring {label} {key}={raw!r} -- not a finite number")
        return None
    ok = (lo <= val <= hi) if lo_inclusive else (lo < val <= hi)
    if not ok:
        bound = f"{lo} <= x <= {hi}" if lo_inclusive else f"{lo} < x <= {hi}"
        _warn(f"token-finops: ignoring {label} {key}={raw!r} -- outside {bound}")
        return None
    return val


# --------------------------------------------------------------------------- #
# Thresholds
# --------------------------------------------------------------------------- #
def thresholds() -> tuple[float, float]:
    """(warn_at, critical_at) as fractions of the window. Resolved together, because
    a `warn_at` above `critical_at` is nonsense even when both values are individually
    in range -- in that case *both* fall back so the pair stays coherent."""
    warn = DEFAULT_WARN_AT
    for label, raw in _sources(None, ENV_WARN_AT, _budget("warn_at"), "budget.warn_at"):
        val = _as_float(label, "warn_at", raw, lo=0.0, hi=1.0)
        if val is not None:
            warn = val
            break
    crit = DEFAULT_CRITICAL_AT
    for label, raw in _sources(None, ENV_CRITICAL_AT, _budget("critical_at"), "budget.critical_at"):
        val = _as_float(label, "critical_at", raw, lo=0.0, hi=1.0)
        if val is not None:
            crit = val
            break
    if not warn < crit:
        _warn(f"token-finops: ignoring budget thresholds warn_at={warn} / critical_at={crit} -- "
              f"warn_at must be below critical_at; using {DEFAULT_WARN_AT}/{DEFAULT_CRITICAL_AT}")
        return DEFAULT_WARN_AT, DEFAULT_CRITICAL_AT
    return warn, crit


def warn_at() -> float:
    return thresholds()[0]


def critical_at() -> float:
    return thresholds()[1]


# --------------------------------------------------------------------------- #
# Cycle day (CALENDAR_MONTH_UTC)
# --------------------------------------------------------------------------- #
def cycle_day() -> int:
    for label, raw in _sources("cycle_day", ENV_CYCLE_DAY, _budget("cycle_day"), "budget.cycle_day"):
        try:
            val = int(raw)
        except (TypeError, ValueError):
            _warn(f"token-finops: ignoring {label} cycle_day={raw!r} -- not an integer")
            continue
        if not 1 <= val <= MAX_CYCLE_DAY:
            _warn(f"token-finops: ignoring {label} cycle_day={raw!r} -- must be 1..{MAX_CYCLE_DAY} "
                  f"(a day that exists in every month)")
            continue
        return val
    return DEFAULT_CYCLE_DAY


# --------------------------------------------------------------------------- #
# Allowance
# --------------------------------------------------------------------------- #
def allowance(tool: str) -> Optional[float]:
    """Configured allowance for `tool` in its native unit, or None (= keep the
    adapter's own default). Copilot has its own flag/env pair (`--budget` /
    `$TOKEN_FINOPS_BUDGET`) because its allowance is the one everybody sets."""
    cli_key = "copilot_allowance" if tool == "copilot" else "allowance"
    env_name = ENV_BUDGET if tool == "copilot" else ENV_ALLOWANCE
    cfg = _budget("allowance")
    if isinstance(cfg, dict):
        cfg = cfg.get(tool)
    elif not isinstance(cfg, (int, float)) or isinstance(cfg, bool):
        cfg = None
    for label, raw in _sources(cli_key, env_name, cfg, f"budget.allowance[{tool}]",
                              "--budget" if tool == "copilot" else "--allowance"):
        val = _as_float(label, f"allowance[{tool}]", raw, lo=0.0, hi=float("1e15"))
        if val is not None:
            return val
    return None


# --------------------------------------------------------------------------- #
# Rolling window length
# --------------------------------------------------------------------------- #
def _window_hours_config(tool: str, window_id: str) -> Any:
    cfg = _budget("window_hours")
    if isinstance(cfg, dict):
        # exact "<tool>:<window_id>" first, then a whole-tool "<tool>" entry
        return cfg.get(f"{tool}:{window_id}", cfg.get(tool))
    if isinstance(cfg, (int, float)) and not isinstance(cfg, bool):
        return cfg
    return None


def _window_hours_env(tool: str, window_id: str) -> Any:
    """`TOKEN_FINOPS_WINDOW_HOURS` is either a bare number (every rolling window) or a
    comma-separated `key=hours` list using the same keys as the config file, e.g.
    `claude_code:5h=26,codex=30`."""
    raw = os.environ.get(ENV_WINDOW_HOURS)
    if not raw:
        return None
    if "=" not in raw:
        return raw
    table = {}
    for chunk in raw.split(","):
        if "=" not in chunk:
            _warn(f"token-finops: ignoring ${ENV_WINDOW_HOURS} entry {chunk!r} -- expected key=hours")
            continue
        key, _, val = chunk.partition("=")
        table[key.strip()] = val.strip()
    return table.get(f"{tool}:{window_id}", table.get(tool))


def window_length(tool: str, window_id: str, default: Optional[timedelta]) -> Optional[timedelta]:
    """Override for a ROLLING window's length. Applied in `BudgetPolicy.__post_init__`
    so it reaches every adapter without any of them knowing about it."""
    sources = []
    env_raw = _window_hours_env(tool, window_id)
    if env_raw is not None:
        sources.append((f"${ENV_WINDOW_HOURS}", env_raw))
    cfg_raw = _window_hours_config(tool, window_id)
    if cfg_raw is not None:
        sources.append(("config.json budget.window_hours", cfg_raw))
    for label, raw in sources:
        val = _as_float(label, f"window_hours[{tool}:{window_id}]", raw, lo=0.0, hi=24 * 366)
        if val is not None:
            return timedelta(hours=val)
    return default


# --------------------------------------------------------------------------- #
# Default tool ("default agent")
# --------------------------------------------------------------------------- #
def default_tool(valid: Optional[Iterable[str]] = None) -> Optional[str]:
    """The tool `--tool` defaults to when the user passes none, or None for the
    historical "all detected tools" behaviour. A name no adapter answers to is
    ignored with a warning rather than producing a silently empty report."""
    known = set(valid) if valid is not None else None
    cfg = load_config().get("default_tool")
    if not isinstance(cfg, str):
        if cfg is not None:
            _warn(f"token-finops: ignoring config.json default_tool={cfg!r} -- must be a string")
        cfg = None
    for label, raw in ((f"${ENV_DEFAULT_TOOL}", os.environ.get(ENV_DEFAULT_TOOL) or None),
                       ("config.json default_tool", cfg)):
        if not raw:
            continue
        name = str(raw).strip()
        if known is not None and name not in known:
            _warn(f"token-finops: ignoring {label} default_tool={name!r} -- no such tool "
                  f"(known: {', '.join(sorted(known))})")
            continue
        return name
    return None
