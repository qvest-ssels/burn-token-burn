"""End-to-end matrix: every supported tool x every synthetic scenario, driven
through the *real* CLI as a subprocess.

This is the layer above `tests/test_synth.py` (which scans the synthetic tree
through adapter objects in-process) and `tests/test_usecases.py` (which drives
`main()` in-process): here the CLI runs as `python -m token_finops_cli` in a
fresh interpreter with nothing but `synth.env.env_for()` pointing it at a
generated fake home, exactly as the documented
`eval "$(token-finops synth --print-env)" && token-finops report` one-liner
does. Import-time constants (`claude_code.QUOTA_FILE`, `status.CACHE_FILE`)
therefore resolve from the synthetic HOME without any monkeypatching, which is
the thing an in-process test cannot prove.

One fake home is generated per scenario (session-scoped, cached) and reused by
every test in this module, so the whole matrix stays a few seconds.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from token_finops_cli.synth import ALL_TOOLS, generate
from token_finops_cli.synth.env import env_for
from token_finops_cli.synth.scenarios import KNOWN as SCENARIOS

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
SEED = 4242
DAYS = 14
# One clock for the whole module: every home is generated relative to the same
# "now", so a scenario's day offsets line up with what the CLI sees at runtime.
NOW = datetime.now(timezone.utc)

STATUSES = {"OK", "WARN", "CRITICAL", "EXHAUSTED", "UNLIMITED", "UNKNOWN"}
CALM = {"OK", "UNKNOWN", "UNLIMITED"}
STRESSED = {"CRITICAL", "EXHAUSTED"}
# Tools whose runway is bounded by a real allowance (Copilot's AI units,
# Codex's provider-reported rolling-window percentage).
RUNWAY_TOOLS = ("copilot", "codex")
# Tools that carry an allowance out of the box and therefore show up in
# `status` without `--all` (the rest are BYO-key, hence UNLIMITED).
ALLOWANCE_TOOLS = ("copilot", "claude_code", "codex", "gemini_cli")
# The synthetic Copilot generator bills ~900 AI units per request, so 14 days
# of "steady" already exceeds the 50,000 AIU default allowance. Give the matrix
# an allowance the fixture's own scale can sit under, so "steady" vs
# "exhausted" (25x the per-event cost) is a real difference and not a floor.
COPILOT_BUDGET = "500000"

# Environment overrides that must not leak in from the developer's shell and
# point an adapter back at real telemetry.
_LEAKY_ENV = ("TOKEN_FINOPS_DB", "TOKEN_FINOPS_AIDER_ANALYTICS", "CLINE_CLI_HOME", "APPDATA")


def _display_names() -> dict[str, str]:
    from token_finops_cli.adapters import all_adapters
    from token_finops_cli.adapters.base import registry

    all_adapters()  # populate the registry
    return {tool: cls.display_name for tool, cls in registry.items()}


DISPLAY = _display_names()


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def synth_homes(tmp_path_factory):
    """`homes(scenario) -> (home_dir, manifest)`, generated once per scenario."""
    root = tmp_path_factory.mktemp("e2e-matrix")
    cache: dict[str, tuple[str, dict]] = {}

    def _home(scenario: str) -> tuple[str, dict]:
        if scenario not in cache:
            out = str(root / scenario)
            manifest = generate(out, days=DAYS, seed=SEED, scenario=scenario, now=NOW)
            cache[scenario] = (out, manifest)
        return cache[scenario]

    return _home


def cli(home: str, *args: str, expect_ok: bool = True) -> str:
    """Run `python -m token_finops_cli <args>` against the synthetic home."""
    env = dict(os.environ)
    for var in _LEAKY_ENV:
        env.pop(var, None)
    env.update(env_for(home))
    env["PYTHONPATH"] = SRC
    proc = subprocess.run([sys.executable, "-m", "token_finops_cli", *args],
                          env=env, capture_output=True, text=True, timeout=120)
    if expect_ok:
        assert proc.returncode == 0, f"{args} exited {proc.returncode}\n{proc.stderr}"
        assert "Traceback" not in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stdout, proc.stdout
    return proc.stdout


def _report_json(home: str, tool: str) -> list[dict]:
    args = ["report", "--tool", tool, "--json"]
    if tool == "copilot":
        args += ["--budget", COPILOT_BUDGET]
    out = cli(home, *args)
    return json.loads(out)  # strict: no NaN/Infinity, no trailing prose


def _session_rows(output: str) -> list[str]:
    """Data rows of a `sessions` table (everything under its header line)."""
    rows: list[str] = []
    in_table = False
    for line in output.splitlines():
        if line.strip().startswith("session ") and "calls" in line:
            in_table = True
            continue
        if not line.strip():
            in_table = False
            continue
        if in_table:
            rows.append(line)
    return rows


# --------------------------------------------------------------------------- #
# adapters: every generated tool is detected
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_adapters_finds_every_generated_tool(synth_homes, scenario):
    home, manifest = synth_homes(scenario)
    out = cli(home, "adapters")
    found = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            found[parts[0]] = parts[1]
    for tool in manifest:
        assert found.get(tool) == "yes", f"{tool} not detected in {scenario}: {out}"


# --------------------------------------------------------------------------- #
# report --json / report (text) / sessions, per tool
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tool", ALL_TOOLS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_report_json_one_object_per_tool(synth_homes, scenario, tool):
    home, _ = synth_homes(scenario)
    payload = _report_json(home, tool)
    assert len(payload) == 1, f"{tool}/{scenario}: expected exactly one row, got {payload}"
    row = payload[0]
    assert row["tool"] == tool
    assert row["display_name"] == DISPLAY[tool]
    assert row["status"] in STATUSES
    assert row["unit"] and row["window"]
    # `used` is a local sum and must never come back negative or non-numeric.
    assert isinstance(row["used"], (int, float)) and row["used"] >= 0


@pytest.mark.parametrize("tool", ALL_TOOLS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_report_text_mentions_the_tool(synth_homes, scenario, tool):
    home, _ = synth_homes(scenario)
    out = cli(home, "report", "--tool", tool)
    assert DISPLAY[tool] in out
    assert "No supported tool data found" not in out


@pytest.mark.parametrize("tool", ALL_TOOLS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_sessions_lists_at_least_one_session(synth_homes, scenario, tool):
    home, _ = synth_homes(scenario)
    out = cli(home, "sessions", "--tool", tool)
    assert "No sessions found." not in out
    assert DISPLAY[tool] in out
    assert len(_session_rows(out)) >= 1, out


# --------------------------------------------------------------------------- #
# scenarios actually move the runway
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tool", RUNWAY_TOOLS)
def test_exhausted_scenario_stresses_runway_tools(synth_homes, tool):
    calm_home, _ = synth_homes("steady")
    hot_home, _ = synth_homes("exhausted")
    assert _report_json(calm_home, tool)[0]["status"] in CALM
    assert _report_json(hot_home, tool)[0]["status"] in STRESSED


def test_binding_constraint_is_reported_across_tools(synth_homes):
    home, _ = synth_homes("exhausted")
    out = cli(home, "report", "--compact", "--budget", COPILOT_BUDGET)
    assert "binding constraint:" in out


# --------------------------------------------------------------------------- #
# status (the cached one-liner surface) over the whole home
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_status_fresh_json_covers_every_tool(synth_homes, scenario):
    home, manifest = synth_homes(scenario)
    snap = json.loads(cli(home, "status", "--fresh", "--format", "json",
                          "--budget", COPILOT_BUDGET))
    assert snap["schema_version"] == 1
    listed = {t["tool"] for t in snap["tools"]}
    # Without --all, exactly the allowance-bearing tools are shown, and each
    # one carries the numbers a status bar needs.
    assert listed == set(ALLOWANCE_TOOLS)
    for row in snap["tools"]:
        assert row["allowance"] is not None
        assert row["used_fraction"] is not None
        assert row["status"] in STATUSES

    all_snap = json.loads(cli(home, "status", "--fresh", "--all", "--format", "json",
                              "--budget", COPILOT_BUDGET))
    assert {t["tool"] for t in all_snap["tools"]} == set(manifest)
    # `--fresh` must have written the cache into the synthetic HOME, not ~/.
    assert os.path.exists(os.path.join(home, ".token-finops", "last.json"))


# --------------------------------------------------------------------------- #
# manifest vs. what the adapters actually see
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_manifest_event_counts_match_the_adapters(synth_homes, scenario, monkeypatch):
    home, manifest = synth_homes(scenario)
    for var, val in env_for(home).items():
        monkeypatch.setenv(var, val)
    for var in _LEAKY_ENV:
        monkeypatch.delenv(var, raising=False)

    from token_finops_cli.adapters import all_adapters

    scanned = {ad.tool: len(ad.events()) for ad in all_adapters() if ad.available()}
    for tool, info in manifest.items():
        assert tool in scanned, f"{tool} unavailable in {scenario}"
        expected = info.get("events")
        if expected:
            assert scanned[tool] == expected, f"{tool}/{scenario}: manifest {expected} != {scanned[tool]}"
        else:
            assert scanned[tool] >= 1


# --------------------------------------------------------------------------- #
# self-audit (Claude Code): sub-agents and content-block dedup
# --------------------------------------------------------------------------- #
def _raw_assistant_lines(home: str, session_id: str) -> int:
    """Lines in the generated transcripts of one session that are assistant
    records — the pre-dedup count (Claude Code writes one line per content
    block of the same API response)."""
    project = os.path.join(home, ".claude", "projects", "-home-demo-project")
    paths = [os.path.join(project, f"{session_id}.jsonl")]
    subagents = os.path.join(project, session_id, "subagents")
    if os.path.isdir(subagents):
        paths += [os.path.join(subagents, n) for n in sorted(os.listdir(subagents))]
    total = 0
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            total += sum(1 for line in fh if '"type": "assistant"' in line)
    return total


@pytest.mark.parametrize("scenario", ["steady", "subagent-heavy"])
def test_self_audit_dedups_content_blocks(synth_homes, scenario):
    home, _ = synth_homes(scenario)
    audit = json.loads(cli(home, "self-audit", "--json"))
    raw = _raw_assistant_lines(home, audit["session"])
    assert raw > 0
    assert audit["calls"] == audit["main"] + audit["subagents"]
    assert audit["calls"] < raw, f"no dedup: {audit['calls']} calls vs {raw} raw lines"
    assert audit["by_model"]


def test_self_audit_sees_subagents_in_subagent_heavy(synth_homes):
    home, _ = synth_homes("subagent-heavy")
    audit = json.loads(cli(home, "self-audit", "--json"))
    assert audit["subagents"] > 0
    text = cli(home, "self-audit")
    assert "Sub-agents:" in text
    assert "sub-agents = " in text


# --------------------------------------------------------------------------- #
# break-even over the whole home
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scenario", ["steady", "burst", "quiet"])
def test_break_even_runs_over_the_whole_home(synth_homes, scenario):
    home, _ = synth_homes(scenario)
    out = cli(home, "break-even")
    assert "Break-even replay" in out


# --------------------------------------------------------------------------- #
# determinism / re-generation
# --------------------------------------------------------------------------- #
_VOLATILE = ("runway_days", "days_left", "resets_at", "time_fraction", "pace_ratio",
             "burn_per_day_avg", "burn_per_day_ema", "notes")


def _stable(payload: list[dict]) -> list[dict]:
    """Drop everything that is a function of the wall clock rather than of the
    generated data (two subprocesses never run at the same instant)."""
    return [{k: v for k, v in row.items() if k not in _VOLATILE} for row in payload]


def test_same_seed_and_now_produce_identical_reports(tmp_path):
    now = NOW
    homes = []
    for name in ("a", "b"):
        out = str(tmp_path / name)
        generate(out, days=10, seed=99, scenario="steady", now=now)
        homes.append(out)
    first, second = (json.loads(cli(h, "report", "--json", "--budget", COPILOT_BUDGET))
                     for h in homes)
    # display_name/used/allowance/used_fraction/status must match exactly;
    # only the paths differ between the two trees, and paths are not reported.
    assert _stable(first) == _stable(second)
    assert {row["tool"] for row in first} == set(ALL_TOOLS)


def test_regenerating_into_an_existing_dir_does_not_crash(tmp_path):
    out = str(tmp_path / "twice")
    first = generate(out, days=6, seed=7, scenario="steady", now=NOW)
    second = generate(out, days=6, seed=7, scenario="burst", now=NOW)
    assert set(first) == set(second) == set(ALL_TOOLS)
    payload = json.loads(cli(out, "report", "--json", "--budget", COPILOT_BUDGET))
    assert {row["tool"] for row in payload} == set(ALL_TOOLS)
    # the SQLite-backed tools must have been rebuilt, not appended to
    assert next(r for r in payload if r["tool"] == "copilot")["used"] > 0
