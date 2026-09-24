"""T-03: the opt-in `--online` quota fetchers.

Every test here stubs `urllib.request.urlopen`; the autouse `no_network` fixture in
conftest.py makes an un-stubbed call raise `NetworkCallAttempted` (a BaseException, so
`online_quota`'s fail-closed `except Exception` cannot hide it), which is what keeps CI
off the real endpoints.

The properties under test are the three non-negotiable ones from AGENTS.md:
opt-in only, fail closed on *every* error, and cached >= 180 s.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from token_finops_cli import online
from token_finops_cli.core.model import QuotaSnapshot

COPILOT_BODY = {
    "quota_snapshots": {"chat": {"percent_remaining": 40.0, "entitlement": 1500, "remaining": 600}},
    "quota_reset_date": "2026-10-01T00:00:00Z",
}
ANTHROPIC_BODY = {"five_hour": {"utilization": 62.0, "resets_at": "2026-09-22T17:00:00Z"},
                  "seven_day": {"utilization": 12.5}}
GEMINI_BODY = {"buckets": [{"remainingFraction": 0.8, "resetTime": "2026-09-23T07:00:00Z"},
                           {"remainingFraction": 0.25, "resetTime": "2026-09-23T07:00:00Z"}]}
OPENROUTER_BODY = {"data": {"usage": 7.5, "limit": 30.0, "limit_remaining": 22.5}}


class _Response(io.BytesIO):
    """The context-manager shape `urllib.request.urlopen` returns."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def stub_urlopen(monkeypatch, body, calls: list | None = None):
    """Answer every request with `body` (a dict, bytes, or an exception to raise)."""
    def _urlopen(req, timeout=None):
        if calls is not None:
            calls.append({"url": req.full_url, "method": req.get_method(),
                          "headers": {k.lower(): v for k, v in req.header_items()},
                          "body": req.data})
        if isinstance(body, BaseException):
            raise body
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return _Response(raw)

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    return calls


@pytest.fixture
def creds(monkeypatch, tmp_path):
    """Credentials for all four tools, in the places the fetchers read them from.
    Nothing here is ever written back -- these are plain fixture files."""
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    claude = tmp_path / "claude"
    claude.mkdir()
    (claude / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oauth"}}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    gem = tmp_path / "gemini"
    gem.mkdir()
    (gem / "oauth_creds.json").write_text(json.dumps({"access_token": "ya29.x"}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_CLI_HOME", str(gem))
    return tmp_path


# --------------------------------------------------------------------------- #
# The happy path, per tool
# --------------------------------------------------------------------------- #
def test_copilot_percent_remaining_becomes_used_fraction(monkeypatch, creds):
    calls = stub_urlopen(monkeypatch, COPILOT_BODY, [])
    snap = online.fetch_copilot_online()
    assert isinstance(snap, QuotaSnapshot)
    assert snap.tool == "copilot" and snap.window_id == "month"
    assert snap.used_fraction == pytest.approx(0.6)        # 100 - 40 % remaining
    assert snap.used_units == pytest.approx(900.0) and snap.limit_units == pytest.approx(1500.0)
    assert snap.resets_at.year == 2026 and snap.resets_at.month == 10
    assert snap.source == "copilot_online"                  # distinct from the offline sources
    assert calls[0]["url"] == online.COPILOT_URL and calls[0]["method"] == "GET"
    assert calls[0]["headers"]["authorization"] == "token gh-token"


def test_anthropic_sends_the_oauth_beta_header_and_reads_both_windows(monkeypatch, creds):
    calls = stub_urlopen(monkeypatch, ANTHROPIC_BODY, [])
    snap = online.fetch_claude_online()
    assert snap.tool == "claude_code" and snap.window_id == "5h"
    assert snap.used_fraction == pytest.approx(0.62)
    assert snap.source == "claude_oauth_usage"
    assert calls[0]["headers"]["anthropic-beta"] == online.ANTHROPIC_BETA
    assert calls[0]["headers"]["authorization"] == "Bearer sk-ant-oauth"
    # the 7d window comes out of the same cached response (one request, two windows)
    assert online.fetch_claude_online("seven_day").window_id == "7d"
    assert len(calls) == 1


def test_anthropic_accepts_a_0_to_1_fraction_as_well_as_a_percentage():
    assert online.parse_anthropic({"five_hour": {"utilization": 0.4}}).used_fraction == pytest.approx(0.4)
    assert online.parse_anthropic({"rate_limits": {"fiveHour": {"used_percentage": 40}}}) \
        .used_fraction == pytest.approx(0.4)


def test_gemini_posts_and_takes_the_emptiest_bucket(monkeypatch, creds):
    calls = stub_urlopen(monkeypatch, GEMINI_BODY, [])
    snap = online.fetch_gemini_online()
    assert snap.tool == "gemini_cli" and snap.window_id == "day"
    assert snap.used_fraction == pytest.approx(0.75)        # 1 - min(remainingFraction)
    assert snap.source == "gemini_online"
    assert calls[0]["method"] == "POST" and calls[0]["body"] == b"{}"
    assert calls[0]["url"] == online.GEMINI_URL


def test_openrouter_reports_dollars_and_a_fraction(monkeypatch, creds):
    stub_urlopen(monkeypatch, OPENROUTER_BODY)
    snap = online.fetch_openrouter_online()
    assert snap.tool == "hermes" and snap.window_id == "30d"
    assert snap.used_units == pytest.approx(7.5) and snap.limit_units == pytest.approx(30.0)
    assert snap.used_fraction == pytest.approx(0.25) and snap.source == "openrouter_key"


def test_openrouter_key_without_a_credit_limit_has_usage_but_no_fraction():
    snap = online.parse_openrouter({"data": {"usage": 3.0, "limit": None, "limit_remaining": None}})
    assert snap.used_units == pytest.approx(3.0) and snap.used_fraction is None


# --------------------------------------------------------------------------- #
# Fail closed — every one of these must return None, never raise
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("failure", [
    urllib.error.URLError("no route to host"),                      # offline machine
    urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None),  # the Anthropic reality
    urllib.error.HTTPError("u", 401, "Unauthorized", {}, None),     # expired token
    TimeoutError("timed out"),
    ConnectionResetError("reset by peer"),
])
@pytest.mark.parametrize("tool", sorted(online.FETCHERS))
def test_network_failures_fall_back_to_none(monkeypatch, creds, tool, failure):
    stub_urlopen(monkeypatch, failure)
    assert online.online_quota(tool) is None


@pytest.mark.parametrize("body", [
    b"<html>503 Service Unavailable</html>",     # not JSON at all
    b"",                                          # empty body
    b'["not", "an", "object"]',                  # JSON, wrong type
    {},                                           # object, no quota in it
    {"quota_snapshots": {"chat": {}}},           # right shape, missing the number
    {"quota_snapshots": "drifted-to-a-string"},  # schema drift
    {"buckets": [{"remainingFraction": "n/a"}]},  # unparsable number
])
@pytest.mark.parametrize("tool", sorted(online.FETCHERS))
def test_unexpected_response_shapes_fall_back_to_none(monkeypatch, creds, tool, body):
    stub_urlopen(monkeypatch, body)
    assert online.online_quota(tool) is None


@pytest.mark.parametrize("tool", sorted(online.FETCHERS))
def test_missing_credentials_never_hit_the_network(monkeypatch, tmp_path, tool):
    """No token anywhere -> no request at all (the autouse guard would raise), None."""
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "OPENROUTER_API_KEY", "OPENROUTER_KEY"):
        monkeypatch.delenv(var, raising=False)
    for var in ("CLAUDE_CONFIG_DIR", "GEMINI_CLI_HOME", "HERMES_HOME"):
        monkeypatch.setenv(var, str(tmp_path / f"no-{var.lower()}"))
    monkeypatch.setattr(online, "github_token", lambda: None)   # no `gh` subprocess either
    assert online.online_quota(tool) is None


def test_a_fetcher_that_raises_anything_still_fails_closed(monkeypatch):
    def boom():
        raise RuntimeError("the endpoint changed shape in a way nobody predicted")

    monkeypatch.setitem(online.FETCHERS, "copilot", boom)
    assert online.online_quota("copilot") is None


def test_unknown_tool_has_no_fetcher():
    assert online.online_quota("codex") is None
    assert online.online_quota("aider") is None


def test_a_fetcher_returning_a_non_snapshot_is_ignored(monkeypatch):
    monkeypatch.setitem(online.FETCHERS, "copilot", lambda: {"used_fraction": 0.9})
    assert online.online_quota("copilot") is None


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
def test_second_call_inside_the_ttl_is_served_from_cache(monkeypatch, creds):
    calls = stub_urlopen(monkeypatch, COPILOT_BODY, [])
    assert online.fetch_copilot_online().used_fraction == pytest.approx(0.6)
    assert online.fetch_copilot_online().used_fraction == pytest.approx(0.6)
    assert len(calls) == 1, "the 180s cache must not re-request inside the TTL"
    assert online.CACHE_TTL_SECONDS >= 180


def test_cache_expires_after_the_ttl(monkeypatch, creds):
    calls = stub_urlopen(monkeypatch, COPILOT_BODY, [])
    online.fetch_copilot_online()
    clock = [online.time.time() + online.CACHE_TTL_SECONDS + 1]
    monkeypatch.setattr(online.time, "time", lambda: clock[0])
    online.fetch_copilot_online()
    assert len(calls) == 2


def test_failures_are_cached_too_so_a_polled_statusline_stops_retrying(monkeypatch, creds):
    calls = stub_urlopen(monkeypatch, urllib.error.URLError("offline"), [])
    assert online.fetch_copilot_online() is None
    assert online.fetch_copilot_online() is None
    assert len(calls) == 1


def test_a_corrupt_cache_file_is_a_miss_not_an_error(monkeypatch, creds):
    with open(online.cache_path(), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    calls = stub_urlopen(monkeypatch, COPILOT_BODY, [])
    assert online.fetch_copilot_online().used_fraction == pytest.approx(0.6)
    assert len(calls) == 1
    assert online.cache_get("copilot") is not None          # and it was rewritten cleanly


def test_an_unwritable_cache_directory_does_not_break_the_fetch(monkeypatch, creds):
    monkeypatch.setenv(online.CACHE_ENV, "/proc/definitely/not/writable/cache.json")
    stub_urlopen(monkeypatch, COPILOT_BODY)
    assert online.fetch_copilot_online().used_fraction == pytest.approx(0.6)


def test_the_cache_never_stores_a_credential(monkeypatch, creds):
    stub_urlopen(monkeypatch, COPILOT_BODY)
    online.fetch_copilot_online()
    stub_urlopen(monkeypatch, ANTHROPIC_BODY)
    online.fetch_claude_online()
    with open(online.cache_path(), encoding="utf-8") as fh:
        raw = fh.read()
    assert "gh-token" not in raw and "sk-ant-oauth" not in raw


def test_cache_entries_are_per_tool(monkeypatch, creds):
    stub_urlopen(monkeypatch, COPILOT_BODY)
    online.fetch_copilot_online()
    stub_urlopen(monkeypatch, OPENROUTER_BODY)
    assert online.fetch_openrouter_online().used_units == pytest.approx(7.5)
    assert set(json.load(open(online.cache_path(), encoding="utf-8"))) == {"copilot", "hermes"}


# --------------------------------------------------------------------------- #
# Credentials are read, never written
# --------------------------------------------------------------------------- #
def test_github_token_prefers_the_env_var_over_the_gh_subprocess(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    monkeypatch.setattr(online.subprocess, "run",
                        lambda *a, **k: pytest.fail("gh must not run when $GITHUB_TOKEN is set"))
    assert online.github_token() == "from-env"


def test_github_token_falls_back_to_gh_auth_token(monkeypatch):
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    seen = {}

    class _Done:
        returncode, stdout = 0, "gho_fromgh\n"

    def _run(cmd, **kw):
        seen["cmd"] = cmd
        return _Done()

    monkeypatch.setattr(online.subprocess, "run", _run)
    assert online.github_token() == "gho_fromgh"
    assert seen["cmd"] == ["gh", "auth", "token"], "only the read-only `gh auth token` is allowed"


def test_github_token_is_none_when_gh_is_absent_or_logged_out(monkeypatch):
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(online.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert online.github_token() is None

    class _Failed:
        returncode, stdout = 1, ""

    monkeypatch.setattr(online.subprocess, "run", lambda *a, **k: _Failed())
    assert online.github_token() is None


def test_credential_files_are_only_read(monkeypatch, creds):
    """The fetchers must not rewrite or refresh a credential file (ground rule 1)."""
    paths = [creds / "claude" / ".credentials.json", creds / "gemini" / "oauth_creds.json"]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    stub_urlopen(monkeypatch, ANTHROPIC_BODY)
    online.fetch_claude_online()
    stub_urlopen(monkeypatch, GEMINI_BODY)
    online.fetch_gemini_online()
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before


def test_nested_and_flat_credential_shapes_both_work(monkeypatch, tmp_path):
    claude = tmp_path / "flat"
    claude.mkdir()
    (claude / ".credentials.json").write_text(json.dumps({"access_token": "flat-token"}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    assert online.anthropic_token() == "flat-token"
    (claude / ".credentials.json").write_text("{corrupt", encoding="utf-8")
    assert online.anthropic_token() is None


def test_openrouter_key_can_come_from_hermes_config(monkeypatch, tmp_path):
    for var in ("OPENROUTER_API_KEY", "OPENROUTER_KEY"):
        monkeypatch.delenv(var, raising=False)
    hermes = tmp_path / "hermes"
    hermes.mkdir()
    (hermes / "config.json").write_text(json.dumps({"providers": {"openrouter": {"api_key": "or-cfg"}}}),
                                        encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    assert online.openrouter_key() == "or-cfg"


# --------------------------------------------------------------------------- #
# CLI wiring: opt-in only
# --------------------------------------------------------------------------- #
def _copilot_args(tmp_path, **over):
    import argparse

    from conftest import NOW, write_copilot_db

    db = tmp_path / "session-store.db"
    if not db.exists():   # the same fixture db is reused across calls within one test
        write_copilot_db(db, [{"ts": NOW, "nano_aiu": 300 * 10**9}])
    base = dict(tool=["copilot"], compact=True, json=False, watch=None, since="7d",
                db_path=str(db), online=False, budget=None, allowance=None, cycle_day=None)
    base.update(over)
    return argparse.Namespace(**base)


def test_report_does_not_go_online_without_the_flag(tmp_path, monkeypatch, home):
    from token_finops_cli import cli

    monkeypatch.setattr(online, "online_quota",
                        lambda tool: pytest.fail("--online was not passed; nothing may be fetched"))
    assert "Copilot" in cli.cmd_report(_copilot_args(tmp_path))


def test_report_online_applies_the_live_quota_over_the_offline_one(tmp_path, monkeypatch, home):
    from token_finops_cli import cli
    from token_finops_cli.core.model import QuotaSnapshot as QS
    from conftest import NOW

    live = QS(tool="copilot", window_id="month", observed_at=NOW, used_fraction=0.93,
              source="copilot_online")
    monkeypatch.setattr(online, "online_quota", lambda tool: live)
    payload = cli.collect_report_payload(_copilot_args(tmp_path, online=True, compact=False))
    assert payload[0]["used_fraction"] == pytest.approx(0.93)


def test_report_online_falls_back_silently_when_the_fetch_fails(tmp_path, monkeypatch, home, capsys):
    """The whole point of T-03: `--online` on a machine with no network/credentials
    prints exactly what a plain offline run prints."""
    from token_finops_cli import cli

    offline_out = cli.cmd_report(_copilot_args(tmp_path))
    stub_urlopen(monkeypatch, urllib.error.URLError("no network"))
    monkeypatch.setattr(online, "github_token", lambda: "gh-token")
    online_out = cli.cmd_report(_copilot_args(tmp_path, online=True))
    assert online_out == offline_out
    assert "Traceback" not in capsys.readouterr().err


def test_a_live_quota_outranks_the_local_sum_for_a_local_sum_tool(tmp_path, monkeypatch, home):
    """Copilot's offline policy is `local_sum`; a successful fetch promotes that run
    to `hybrid` so the provider's own number decides used%, and says so in the notes."""
    from token_finops_cli import cli

    stub_urlopen(monkeypatch, COPILOT_BODY)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    rows = cli._report_rows(_copilot_args(tmp_path, online=True, compact=False))
    (_, runway, _) = rows[0]
    assert runway.used_fraction == pytest.approx(0.6)
    assert runway.source_of_truth == "hybrid"
    assert any("copilot_online" in note for note in runway.notes)


def test_report_online_runs_end_to_end_through_the_real_parser(tmp_path, monkeypatch, home, run_cli):
    stub_urlopen(monkeypatch, COPILOT_BODY)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    from conftest import NOW, write_copilot_db

    db = tmp_path / "s.db"
    write_copilot_db(db, [{"ts": NOW, "nano_aiu": 300 * 10**9}])
    out = run_cli("report", "--online", "--db-path", str(db), "--json")
    assert json.loads(out)[0]["used_fraction"] == pytest.approx(0.6)


def test_report_and_status_expose_the_flag_and_default_it_off():
    from token_finops_cli.adapters import all_adapters
    from token_finops_cli.cli import build_parser

    all_adapters()
    parser = build_parser()
    for cmd in ("report", "status"):
        assert parser.parse_args([cmd]).online is False, f"{cmd} --online must default to off"
        assert parser.parse_args([cmd, "--online"]).online is True


def test_status_online_implies_a_rescan(tmp_path, monkeypatch, home):
    """A cached `last.json` was built with the *previous* run's quota source, so
    `--online` must not be answered out of it."""
    import argparse

    from token_finops_cli import status as st

    cache = tmp_path / "last.json"
    st.write_cache(st.build_snapshot([{"tool": "copilot", "display_name": "GitHub Copilot CLI",
                                       "window": "month", "unit": "aiu", "used_fraction": 0.1,
                                       "runway_days": 30.0, "status": "OK"}]), str(cache))
    calls = []
    monkeypatch.setattr("token_finops_cli.cli.collect_report_payload",
                        lambda args: calls.append(args) or [])
    args = argparse.Namespace(cache_file=str(cache), fresh=False, max_age=300, format="plain",
                              tool=None, all=False, online=True, budget=None, allowance=None,
                              cycle_day=None, db_path=None)
    st.cmd_status(args)
    assert calls, "--online must rescan instead of serving the cached snapshot"
    args.online = False
    calls.clear()
    st.cmd_status(args)
    assert not calls, "without --online the cache is still used"
