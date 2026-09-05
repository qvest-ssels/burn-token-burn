import json
import subprocess
import sys

from token_finops_cli.savings import cloud_blended_usd_per_mtok, local_cost


def run(*args, env=None):
    return subprocess.run([sys.executable, "-m", "token_finops_cli", *args], capture_output=True, text=True,
                          check=False, env=env)


def test_help_lists_subcommands():
    r = run("--help")
    assert r.returncode == 0
    for cmd in ("report", "sessions", "self-audit", "savings", "break-even", "collect-statusline", "adapters"):
        assert cmd in r.stdout


def test_adapters_runs():
    r = run("adapters")
    assert r.returncode == 0 and "claude_code" in r.stdout


def test_report_json_on_synthetic_copilot(tmp_path, monkeypatch):
    from token_finops_cli.adapters.copilot import build_synthetic_db
    db = tmp_path / "s.db"
    build_synthetic_db(str(db), days=5, events_per_day=4)
    import os
    env = {**os.environ, "TOKEN_FINOPS_COPILOT_DB": str(db), "PYTHONPATH": "src"}
    r = run("report", "--tool", "copilot", "--budget", "5000", "--json", env=env)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data[0]["tool"] == "copilot" and data[0]["unit"] == "aiu" and data[0]["used"] > 0


def test_savings_formula_consistency():
    lc = local_cost("mac-studio-m4-max-128gb", "qwen3-32b", "grid-de-household", utilization=0.2)
    assert abs(lc.hours_per_mtok - 1e6 / (25 * 3600)) < 1e-9
    assert abs(lc.kwh_per_mtok - 90 * lc.hours_per_mtok / 1000) < 1e-9
    assert lc.total_usd_per_mtok > lc.energy_usd_per_mtok > 0
    cloud = cloud_blended_usd_per_mtok("sonnet")
    be = lc.break_even_utilization(cloud)
    assert be is not None and 0.4 < be < 0.8      # ~60 % in the README example
    # higher utilisation must be cheaper per token
    hi = local_cost("mac-studio-m4-max-128gb", "qwen3-32b", "grid-de-household", utilization=0.8)
    assert hi.total_usd_per_mtok < lc.total_usd_per_mtok


def test_solar_is_not_free():
    grid = local_cost("mac-studio-m4-max-128gb", "qwen3-32b", "grid-de-household")
    solar = local_cost("mac-studio-m4-max-128gb", "qwen3-32b", "solar-de-feed-in")
    assert 0 < solar.energy_usd_per_mtok < grid.energy_usd_per_mtok


def test_savings_cli_list():
    r = run("savings", "--list")
    assert r.returncode == 0 and "mac-studio-m4-max-128gb" in r.stdout and "solar-de-feed-in" in r.stdout
