"""core/pricing.py: model-id normalisation, table lookup, USD estimates and
the two user-override files under ~/.token-finops/."""
from __future__ import annotations

import json

import pytest

from token_finops_cli.core import pricing
from token_finops_cli.core.pricing import (PRICING, PRICING_REVIEW_DATE, estimate_usd, is_local_model, lookup,
                                           normalize_model_id, table)


@pytest.fixture(autouse=True)
def _fresh_table(home):
    """Every test starts from the built-in table only (home redirects ~)."""
    yield


# --------------------------------------------------------------------------- #
# normalize_model_id
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw, norm", [
    ("claude-sonnet-4-5-20250929", "claude-sonnet-4-5"),
    ("claude-3-5-haiku-20241022", "claude-3-5-haiku"),
    ("gpt-5-2025-08-07", "gpt-5"),                      # dashed date
    ("gpt-4o-2024-11-20", "gpt-4o"),
    ("gpt-5_2025_08_07", "gpt-5"),                      # underscore date
    ("anthropic/claude-opus-4-1", "claude-opus-4-1"),
    ("openai/gpt-5-mini", "gpt-5-mini"),
    ("google/gemini-2.5-pro", "gemini-2.5-pro"),
    ("models/gemini-2.5-flash", "gemini-2.5-flash"),
    ("openrouter/qwen3-235b-a22b", "qwen3-235b-a22b"),
    ("vertex_ai/gemini-2.5-pro", "gemini-2.5-pro"),
    ("azure/gpt-4.1", "gpt-4.1"),
    ("us.anthropic.claude-sonnet-4-20250514-v1:0", "claude-sonnet-4"),   # bedrock version + date
    ("eu.anthropic.claude-opus-4-1-20250805-v1:0", "claude-opus-4-1"),
    ("claude-sonnet-4-5-latest", "claude-sonnet-4-5"),
    ("gemini-2.5-pro_latest", "gemini-2.5-pro"),
    ("claude-opus-4@latest", "claude-opus-4"),
    ("Claude_Sonnet_5", "claude-sonnet-5"),             # case + underscores
    ("  GPT-5  ", "gpt-5"),
    ("gpt-5.6-terra", "gpt-5.6-terra"),                 # dots survive
    ("qwen3-235b-a22b", "qwen3-235b-a22b"),             # no false date match
    ("", ""),
    (None, ""),
])
def test_normalize_model_id(raw, norm):
    assert normalize_model_id(raw) == norm


def test_normalize_is_idempotent():
    for raw in list(PRICING) + ["anthropic/claude-sonnet-4-5-20250929", "us.anthropic.claude-sonnet-4-v1:0"]:
        once = normalize_model_id(raw)
        assert normalize_model_id(once) == once


def test_normalize_only_strips_trailing_date():
    # a date in the middle is not a version suffix
    assert normalize_model_id("claude-sonnet-5-20260101-preview") == "claude-sonnet-5-20260101-preview"


def test_normalize_bedrock_ids_with_stacked_prefixes():
    assert normalize_model_id("bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0") == "claude-sonnet-4"
    assert normalize_model_id("anthropic.claude-sonnet-4-20250514-v1:0") == "claude-sonnet-4"


# --------------------------------------------------------------------------- #
# table / lookup
# --------------------------------------------------------------------------- #
def test_table_is_cached_copy_of_pricing():
    t = table()
    assert t == PRICING and t is not PRICING
    assert table() is t                       # cached
    assert PRICING_REVIEW_DATE.count("-") == 2


def test_lookup_exact_prefix_and_miss():
    assert lookup("claude-sonnet-5") is PRICING["claude-sonnet-5"]
    assert lookup("anthropic/claude-sonnet-5-20260101") is PRICING["claude-sonnet-5"]
    # prefix match, longest key wins: gpt-5-mini-preview -> gpt-5-mini, not gpt-5
    assert lookup("gpt-5-mini-preview") is PRICING["gpt-5-mini"]
    assert lookup("gpt-5.6-terra-2026-06-01") is PRICING["gpt-5.6-terra"]
    assert lookup("claude-sonnet-5-20260101-preview") is PRICING["claude-sonnet-5"]
    assert lookup("gpt-5-turbo") is PRICING["gpt-5"]
    assert lookup("totally-unknown-model") is None
    assert lookup("") is None


def test_lookup_prefix_match_is_one_directional():
    # the table key must be a prefix of the queried id, never the other way round
    assert lookup("gpt-4") is None
    assert lookup("o3-pro") is PRICING["o3"]


# --------------------------------------------------------------------------- #
# is_local_model
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model, local", [
    ("ollama/qwen3:latest", True), ("qwen3:latest", True), ("lmstudio/x", True), ("lm-studio/x", True),
    ("vllm/llama", True), ("local/foo", True), ("Qwen3-32B-GGUF", True), ("mlx-community/x", True),
    ("claude-sonnet-5", False), ("gpt-5", False), ("", False), (None, False),
])
def test_is_local_model(model, local):
    assert is_local_model(model) is local


# --------------------------------------------------------------------------- #
# estimate_usd
# --------------------------------------------------------------------------- #
def test_estimate_usd_input_and_output():
    assert estimate_usd("claude-sonnet-5", input_tokens=1_000_000) == pytest.approx(2.0)
    assert estimate_usd("claude-sonnet-5", output_tokens=1_000_000) == pytest.approx(10.0)
    assert estimate_usd("claude-sonnet-5", input_tokens=500_000, output_tokens=100_000) == pytest.approx(2.0)
    assert estimate_usd("claude-sonnet-5") == 0.0


def test_estimate_usd_cache_read_is_ten_percent_of_input():
    assert estimate_usd("claude-sonnet-5", cache_read_tokens=1_000_000) == pytest.approx(0.2)
    assert estimate_usd("gpt-5", cache_read_tokens=1_000_000) == pytest.approx(0.125)
    # Google caches at 25 %
    assert estimate_usd("gemini-2.5-pro", cache_read_tokens=1_000_000) == pytest.approx(1.25 * 0.25)
    # unknown provider falls back to the default 10 %
    assert estimate_usd("gpt-oss-120b", cache_read_tokens=1_000_000) == pytest.approx(0.003)


def test_estimate_usd_cache_write_5m_vs_1h():
    five_min = estimate_usd("claude-sonnet-5", cache_write_tokens=1_000_000)
    one_hour = estimate_usd("claude-sonnet-5", cache_write_tokens=1_000_000, cache_write_1h_tokens=1_000_000)
    mixed = estimate_usd("claude-sonnet-5", cache_write_tokens=1_000_000, cache_write_1h_tokens=400_000)
    assert five_min == pytest.approx(2.0 * 1.25)
    assert one_hour == pytest.approx(2.0 * 2.0)
    assert mixed == pytest.approx(600_000 * 2.5e-6 + 400_000 * 4e-6)
    # non-Anthropic providers: cache write at 1x input, 1h identical
    assert estimate_usd("gpt-5", cache_write_tokens=1_000_000) == pytest.approx(1.25)
    assert estimate_usd("gpt-5", cache_write_tokens=1_000_000, cache_write_1h_tokens=1_000_000) == pytest.approx(1.25)


def test_estimate_usd_unknown_and_local_are_none():
    assert estimate_usd("no-such-model", 1000, 1000) is None
    assert estimate_usd("ollama/qwen3:latest", 1000, 1000) is None
    assert estimate_usd("qwen3-32b-gguf", 1000) is None
    assert estimate_usd("", 1000) is None


def test_estimate_usd_accepts_raw_provider_ids():
    assert estimate_usd("anthropic/claude-haiku-4-5-20260301", input_tokens=1_000_000) == pytest.approx(1.0)
    assert estimate_usd("us.anthropic.claude-opus-4-1-20250805-v1:0", output_tokens=1_000) == pytest.approx(0.075)


# --------------------------------------------------------------------------- #
# overrides
# --------------------------------------------------------------------------- #
def _write(home, name, data):
    d = home / ".token-finops"
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps(data), encoding="utf-8")


def test_pricing_json_override_adds_and_replaces(home):
    _write(home, "pricing.json", {
        "Claude-Sonnet-5-20260101": {"provider": "anthropic", "input": 1.0, "output": 1.0},   # normalised key
        "my-private-model": {"provider": "acme", "input": 100.0, "output": 200.0, "cache_read": 1.0},
    })
    pricing._TABLE = None
    assert estimate_usd("claude-sonnet-5", input_tokens=1_000_000) == pytest.approx(1.0)
    assert lookup("my-private-model")["provider"] == "acme"
    assert estimate_usd("my-private-model", cache_read_tokens=1_000_000) == pytest.approx(1.0)  # explicit
    assert estimate_usd("my-private-model", cache_write_tokens=1_000_000) == pytest.approx(100.0)  # default 1x
    assert lookup("gpt-5") is not None                                                            # rest intact


def test_litellm_file_is_converted_and_overridden_by_pricing_json(home):
    _write(home, "litellm_prices.json", {
        "sample_spec": {"max_tokens": "set to max output tokens"},        # not a price entry
        "anthropic/claude-sonnet-5": {"litellm_provider": "anthropic", "input_cost_per_token": 3e-6,
                                      "output_cost_per_token": 15e-6, "cache_read_input_token_cost": 0.3e-6,
                                      "cache_creation_input_token_cost": 3.75e-6},
        "some-new-model": {"input_cost_per_token": 1e-6},                # no output, no provider
        "weird": "not a dict",
    })
    _write(home, "pricing.json", {"claude-sonnet-5": {"provider": "anthropic", "input": 2.0, "output": 10.0}})
    pricing._TABLE = None
    t = table()
    assert "sample-spec" not in t and "weird" not in t
    new = t["some-new-model"]
    assert new == {"provider": "default", "input": 1.0, "output": 0.0, "cache_read": None, "cache_write": None}
    assert estimate_usd("some-new-model", input_tokens=1_000_000, cache_read_tokens=1_000_000) == pytest.approx(1.1)
    # pricing.json wins over litellm
    assert t["claude-sonnet-5"]["input"] == 2.0


def test_litellm_only_entry_keeps_explicit_cache_prices(home):
    _write(home, "litellm_prices.json", {
        "claude-sonnet-5": {"litellm_provider": "anthropic", "input_cost_per_token": 3e-6,
                            "output_cost_per_token": 15e-6, "cache_read_input_token_cost": 0.3e-6,
                            "cache_creation_input_token_cost": 3.75e-6},
    })
    pricing._TABLE = None
    assert estimate_usd("claude-sonnet-5", cache_read_tokens=1_000_000) == pytest.approx(0.3)
    assert estimate_usd("claude-sonnet-5", cache_write_tokens=1_000_000) == pytest.approx(3.75)
    assert estimate_usd("claude-sonnet-5", output_tokens=1_000_000) == pytest.approx(15.0)


def test_broken_override_files_are_ignored(home):
    d = home / ".token-finops"
    d.mkdir()
    (d / "pricing.json").write_text("{not json", encoding="utf-8")
    (d / "litellm_prices.json").write_text("{broken", encoding="utf-8")
    pricing._TABLE = None
    assert table() == PRICING


@pytest.mark.parametrize("name", ["litellm_prices.json", "pricing.json"])
def test_non_object_override_json_is_ignored(home, name):
    _write(home, name, [])
    pricing._TABLE = None
    assert table() == PRICING


def test_missing_override_files_mean_builtin_table(home):
    pricing._TABLE = None
    assert table() == PRICING
    assert pricing._load_overrides() == {} and pricing._load_litellm() == {}
