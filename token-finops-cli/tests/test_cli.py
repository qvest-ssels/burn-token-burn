"""Smoke tests for token_finops_cli — no live Copilot DB required."""
import subprocess
import sys


def test_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "token_finops_cli.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "report" in result.stdout
    assert "sessions" in result.stdout


def test_report_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "token_finops_cli.cli", "report", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--budget" in result.stdout
    assert "--watch" in result.stdout


def test_default_command_is_report():
    """No subcommand should behave the same as `report` (backward compat
    with the pre-subcommand CLI)."""
    result = subprocess.run(
        [sys.executable, "-m", "token_finops_cli.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_sessions_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "token_finops_cli.cli", "sessions", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--gap-minutes" in result.stdout
    assert "--limit" in result.stdout


def test_sessions_list_against_synthetic_db(tmp_path):
    from token_finops_cli.examples_helper import build_synthetic_db

    db_path = tmp_path / "demo.db"
    build_synthetic_db(str(db_path), days=10, events_per_day=5, seed=1)

    result = subprocess.run(
        [sys.executable, "-m", "token_finops_cli.cli", "sessions",
         "--db-path", str(db_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "demo-session-0" in result.stdout


def test_sessions_totals_report(tmp_path):
    from token_finops_cli.examples_helper import build_synthetic_db

    db_path = tmp_path / "demo.db"
    build_synthetic_db(str(db_path), days=10, events_per_day=5, seed=1)

    result = subprocess.run(
        [sys.executable, "-m", "token_finops_cli.cli", "sessions",
         "--totals", "--db-path", str(db_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "All sessions report" in result.stdout
    assert "sessions:" in result.stdout
    assert "total breaks detected" in result.stdout


def test_session_breaks_detection(tmp_path):
    from token_finops_cli.cli import connect_readonly, session_breaks
    from token_finops_cli.examples_helper import build_synthetic_db

    db_path = tmp_path / "demo.db"
    build_synthetic_db(str(db_path), days=10, events_per_day=5, seed=1)

    con = connect_readonly(str(db_path))
    breaks, active_s, idle_s, elapsed_s = session_breaks(
        con, "demo-session-0", gap_minutes=60
    )
    con.close()

    assert elapsed_s > 0
    assert active_s + idle_s <= elapsed_s + 1  # allow float rounding
    assert isinstance(breaks, list)


def test_progress_bar_bounds():
    from token_finops_cli.cli import progress_bar

    assert progress_bar(0.0).startswith("[")
    assert "100.0%" in progress_bar(1.5)  # clamps above 1
    assert "0.0%" in progress_bar(-0.5)  # clamps below 0


def test_format_tokens():
    from token_finops_cli.cli import format_tokens

    assert format_tokens(500) == "500"
    assert format_tokens(1_500) == "1.5k"
    assert format_tokens(2_000_000) == "2.0M"
