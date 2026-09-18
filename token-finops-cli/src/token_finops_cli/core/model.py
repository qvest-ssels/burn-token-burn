"""Tool-agnostic data model.

Design rule (see docs/guide/02-where-does-the-money-go.md): budgets are
normalised to *fractions of a window*, never to dollars. Dollars are only ever
a secondary, clearly labelled estimate. Heterogeneous units (Copilot AI
credits, Claude %, Gemini requests/day, OpenRouter $) are never summed.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from . import config


class Unit(str, enum.Enum):
    """The native unit a provider budgets in."""

    AIU = "aiu"            # GitHub Copilot "AI units" / credits (1 credit = $0.01)
    USD = "usd"            # pay-per-token API keys, OpenRouter credits
    REQUESTS = "requests"  # Gemini CLI daily request quota
    PERCENT = "percent"    # opaque provider-reported window percentage (Claude, Codex)
    TOKENS = "tokens"      # user-defined token allowance
    MINUTES = "minutes"    # local models: only wall-clock/throughput matters


class CycleKind(str, enum.Enum):
    CALENDAR_MONTH_UTC = "calendar_month_utc"   # Copilot: resets 00:00 UTC on the 1st
    ROLLING = "rolling"                          # Claude/Codex 5h + 7d windows
    DAILY = "daily"                              # Gemini: per-day quota
    SLIDING_FROM_FIRST_USE = "sliding_from_first_use"
    NONE = "none"                                # unlimited / local


class Status(str, enum.Enum):
    OK = "OK"
    WARN = "WARN"
    CRITICAL = "CRITICAL"
    EXHAUSTED = "EXHAUSTED"
    UNLIMITED = "UNLIMITED"
    UNKNOWN = "UNKNOWN"


@dataclass
class UsageEvent:
    """One billable model call, as observed in a tool's local telemetry."""

    ts_utc: datetime
    tool: str                       # "copilot" | "claude_code" | "codex" | "gemini_cli" | "hermes" | ...
    model_raw: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    reasoning_is_subset_of_output: bool = True
    session_id: str = ""
    agent_id: str = ""              # sub-agent identifier if the call was made by a sub-agent
    parent_id: str = ""             # parent tool-call / message id
    initiator: str = ""             # "user" | "agent" | "" (unknown)
    native_cost: Optional[float] = None   # in the tool's native unit (e.g. AIU)
    native_unit: Optional[Unit] = None
    usd_estimate: Optional[float] = None  # secondary estimate via pricing table
    is_local_model: bool = False
    duration_ms: Optional[float] = None
    cwd: str = ""
    event_id: str = ""              # stable id after dedup (adapter-specific composite key)
    tags: dict = field(default_factory=dict)  # adapter extras, e.g. {"first_tool": "Bash"}

    @property
    def model_norm(self) -> str:
        from .pricing import normalize_model_id

        return normalize_model_id(self.model_raw)

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


@dataclass
class QuotaSnapshot:
    """Provider-reported usage of a budget window (authoritative if available)."""

    tool: str
    window_id: str                  # "month" | "5h" | "7d" | "day" | ...
    observed_at: datetime
    used_fraction: Optional[float] = None   # 0..1
    used_units: Optional[float] = None
    limit_units: Optional[float] = None
    resets_at: Optional[datetime] = None
    source: str = ""                # "codex_rollout" | "claude_statusline" | "copilot_internal_user" | ...


@dataclass
class BudgetPolicy:
    """What the user (or provider) says the allowance is and how it resets."""

    tool: str
    window_id: str
    unit: Unit
    cycle: CycleKind
    allowance: Optional[float] = None       # None = unlimited/unknown
    window_length: Optional[timedelta] = None   # for ROLLING
    # The three fields below are user-configurable (`~/.token-finops/config.json`,
    # `TOKEN_FINOPS_*`) -- see core/config.py. They are resolved here, at construction
    # time, so every adapter's `default_policy()` picks the setting up without knowing
    # it exists. Passing an explicit value still wins (that is how a CLI flag lands).
    cycle_day: int = field(default_factory=config.cycle_day)   # for CALENDAR_MONTH_UTC
    warn_at: float = field(default_factory=config.warn_at)
    critical_at: float = field(default_factory=config.critical_at)
    source_of_truth: str = "local_sum"      # "local_sum" | "provider_pct" | "hybrid"

    def __post_init__(self) -> None:
        # A configured rolling-window length is a *fallback for the span we assume*,
        # never a reset time: when a tool reports a real `resets_at` (Claude Code's
        # statusline payload, Codex's rollout rate_limits) the runway engine keeps
        # using that snapshot's timestamp -- see core/runway.py::_percent_runway.
        if self.cycle == CycleKind.ROLLING:
            self.window_length = config.window_length(self.tool, self.window_id, self.window_length)


@dataclass
class Runway:
    """Result of comparing burn against the remaining window."""

    tool: str
    window_id: str
    unit: Unit
    now: datetime
    window_start: datetime
    resets_at: Optional[datetime]
    used: float                             # in native unit (or fraction if PERCENT)
    allowance: Optional[float]
    used_fraction: Optional[float]          # used / allowance
    time_fraction: Optional[float]          # elapsed / window length
    pace_ratio: Optional[float]             # used_fraction / time_fraction (1.0 = exactly on pace)
    burn_per_day_avg: Optional[float]       # cycle average
    burn_per_day_ema: Optional[float]       # recency-weighted
    runway_days: Optional[float]            # remaining / burn (None = infinite)
    days_left: Optional[float]
    projected_exhaustion: Optional[datetime]
    status: Status
    source_of_truth: str = "local_sum"
    notes: list[str] = field(default_factory=list)

    @property
    def is_binding(self) -> bool:
        return self.status in (Status.WARN, Status.CRITICAL, Status.EXHAUSTED)
