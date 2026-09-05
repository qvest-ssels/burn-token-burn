"""Offline pricing snapshot and model-id normalisation.

USD figures are *secondary estimates* ("what this would have cost on the
pay-per-token API"). They are never used to compare across tools that bill in
other units. Update via `~/.token-finops/pricing.json` (same shape as
PRICING below) or by dropping a LiteLLM `model_prices_and_context_window.json`
at `~/.token-finops/litellm_prices.json`.

All prices: USD per 1M tokens. `cache_read` / `cache_write` default to the
provider's usual multiplier of `input` if omitted.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

PRICING_REVIEW_DATE = "2026-09-04"

# provider default multipliers relative to input price
CACHE_READ_MULT = {"anthropic": 0.10, "openai": 0.10, "google": 0.25, "default": 0.10}
CACHE_WRITE_MULT = {"anthropic": 1.25, "default": 1.0}     # Anthropic 5-minute cache
CACHE_WRITE_1H_MULT = {"anthropic": 2.0, "default": 1.0}   # Anthropic 1-hour cache

PRICING: dict[str, dict] = {
    # --- Anthropic (provider "anthropic") ---
    "claude-fable-5-1":   {"provider": "anthropic", "input": 10.0, "output": 50.0},
    "claude-opus-5":      {"provider": "anthropic", "input": 5.0,  "output": 25.0},
    "claude-sonnet-5":    {"provider": "anthropic", "input": 2.0,  "output": 10.0},
    "claude-haiku-4-5":   {"provider": "anthropic", "input": 1.0,  "output": 5.0},
    "claude-opus-4-1":    {"provider": "anthropic", "input": 15.0, "output": 75.0},
    "claude-opus-4":      {"provider": "anthropic", "input": 15.0, "output": 75.0},
    "claude-sonnet-4-5":  {"provider": "anthropic", "input": 3.0,  "output": 15.0},
    "claude-sonnet-4":    {"provider": "anthropic", "input": 3.0,  "output": 15.0},
    "claude-3-5-haiku":   {"provider": "anthropic", "input": 0.8,  "output": 4.0},
    # --- OpenAI ---
    "gpt-5.6-luna":       {"provider": "openai", "input": 0.20, "output": 1.20},
    "gpt-5.6-terra":      {"provider": "openai", "input": 2.0,  "output": 12.0},
    "gpt-5.6-sol":        {"provider": "openai", "input": 5.0,  "output": 30.0},
    "gpt-5":              {"provider": "openai", "input": 1.25, "output": 10.0},
    "gpt-5-mini":         {"provider": "openai", "input": 0.25, "output": 2.0},
    "gpt-5-nano":         {"provider": "openai", "input": 0.05, "output": 0.40},
    "gpt-4.1":            {"provider": "openai", "input": 2.0,  "output": 8.0},
    "gpt-4.1-mini":       {"provider": "openai", "input": 0.40, "output": 1.60},
    "gpt-4o":             {"provider": "openai", "input": 2.5,  "output": 10.0},
    "o3":                 {"provider": "openai", "input": 2.0,  "output": 8.0},
    "o4-mini":            {"provider": "openai", "input": 1.1,  "output": 4.4},
    # --- Google ---
    "gemini-2.5-pro":     {"provider": "google", "input": 1.25, "output": 10.0},
    "gemini-2.5-flash":   {"provider": "google", "input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"provider": "google", "input": 0.10, "output": 0.40},
    # --- Open models via OpenRouter (cheapest tier, indicative) ---
    "gpt-oss-120b":       {"provider": "openrouter", "input": 0.03, "output": 0.17},
    "gpt-oss-20b":        {"provider": "openrouter", "input": 0.02, "output": 0.08},
    "qwen3-235b-a22b":    {"provider": "openrouter", "input": 0.10, "output": 0.30},
    "llama-3.1-8b":       {"provider": "openrouter", "input": 0.02, "output": 0.03},
}

_DATE_SUFFIX = re.compile(r"[-_](?:20\d{2})[-_]?\d{2}[-_]?\d{2}$")
_PREFIXES = ("anthropic/", "openai/", "google/", "openrouter/", "models/", "us.anthropic.",
             "eu.anthropic.", "apac.anthropic.", "anthropic.", "bedrock/", "vertex_ai/", "azure/")


def normalize_model_id(model: str) -> str:
    """'claude-sonnet-4-5-20250929' -> 'claude-sonnet-4-5'; strips provider
    prefixes, date suffixes, 'latest', and Bedrock '-v1:0' style versions."""
    m = (model or "").strip().lower()
    # prefixes can stack (e.g. "bedrock/us.anthropic.claude-…"); strip until none matches
    changed = True
    while changed:
        changed = False
        for p in _PREFIXES:
            if m.startswith(p):
                m = m[len(p):]
                changed = True
    m = re.sub(r"-v\d+:\d+$", "", m)
    m = re.sub(r"[-_@]latest$", "", m)
    m = _DATE_SUFFIX.sub("", m)
    m = m.replace("_", "-")
    return m


def _load_overrides() -> dict:
    path = os.path.expanduser("~/.token-finops/pricing.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {normalize_model_id(k): v for k, v in data.items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def _load_litellm() -> dict:
    path = os.path.expanduser("~/.token-finops/litellm_prices.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if not isinstance(v, dict) or "input_cost_per_token" not in v:
            continue
        out[normalize_model_id(k)] = {
            "provider": v.get("litellm_provider", "default"),
            "input": v["input_cost_per_token"] * 1e6,
            "output": v.get("output_cost_per_token", 0) * 1e6,
            "cache_read": (v.get("cache_read_input_token_cost") or 0) * 1e6 or None,
            "cache_write": (v.get("cache_creation_input_token_cost") or 0) * 1e6 or None,
        }
    return out


_TABLE: Optional[dict] = None


def table() -> dict:
    global _TABLE
    if _TABLE is None:
        t = dict(PRICING)
        t.update(_load_litellm())
        t.update(_load_overrides())
        _TABLE = t
    return _TABLE


def lookup(model: str) -> Optional[dict]:
    norm = normalize_model_id(model)
    t = table()
    if norm in t:
        return t[norm]
    # prefix match: 'claude-sonnet-5-20260101-preview' -> 'claude-sonnet-5'
    for key in sorted(t, key=len, reverse=True):
        if norm.startswith(key):
            return t[key]
    return None


def is_local_model(model: str) -> bool:
    m = (model or "").lower()
    return any(tag in m for tag in ("ollama", "lmstudio", "lm-studio", "vllm", "local/", ":latest",
                                    "gguf", "mlx-community"))


def estimate_usd(model: str, input_tokens: int = 0, output_tokens: int = 0,
                 cache_read_tokens: int = 0, cache_write_tokens: int = 0,
                 cache_write_1h_tokens: int = 0) -> Optional[float]:
    """USD estimate for one call, or None if the model is unknown/local."""
    if is_local_model(model):
        return None
    p = lookup(model)
    if not p:
        return None
    prov = p.get("provider", "default")
    inp = p["input"]
    out = p.get("output", 0.0)
    cr = p.get("cache_read") or inp * CACHE_READ_MULT.get(prov, CACHE_READ_MULT["default"])
    cw = p.get("cache_write") or inp * CACHE_WRITE_MULT.get(prov, CACHE_WRITE_MULT["default"])
    cw1h = inp * CACHE_WRITE_1H_MULT.get(prov, CACHE_WRITE_1H_MULT["default"])
    usd = (input_tokens * inp + output_tokens * out + cache_read_tokens * cr
           + (cache_write_tokens - cache_write_1h_tokens) * cw + cache_write_1h_tokens * cw1h)
    return usd / 1e6
