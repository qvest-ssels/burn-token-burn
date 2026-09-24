"""`status --notify` (T-11): fire a desktop notification only when the binding
constraint's status class changes; never let the OS mechanism crash or block."""
from __future__ import annotations

import json
import subprocess

from token_finops_cli import notify as nt


def snap(status, tool="claude_code", display_name="Claude Code"):
    binding = None if status is None else {
        "tool": tool, "display_name": display_name, "window": "5h",
        "runway_days": 0.2, "used_fraction": 0.6, "status": status,
    }
    return {"schema_version": 1, "generated_at": "2026-09-14T12:00:00+00:00", "tools": [], "binding": binding}


# --------------------------------------------------------------------------- #
# state file
# --------------------------------------------------------------------------- #
def test_state_roundtrip(tmp_path):
    path = tmp_path / "notify-state.json"
    nt.write_state({"last_class": "OK"}, str(path))
    assert nt.read_state(str(path)) == {"last_class": "OK"}


def test_read_state_missing_or_corrupt_is_none(tmp_path):
    assert nt.read_state(str(tmp_path / "missing.json")) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert nt.read_state(str(bad)) is None


# --------------------------------------------------------------------------- #
# maybe_notify: the class-change diff
# --------------------------------------------------------------------------- #
def test_first_run_establishes_baseline_without_notifying(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nt, "send_notification", lambda *a: calls.append(a) or True)
    path = tmp_path / "notify-state.json"
    fired = nt.maybe_notify(snap("OK"), str(path))
    assert fired is False
    assert calls == []
    assert json.loads(path.read_text())["last_class"] == "OK"


def test_no_class_change_does_not_notify(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nt, "send_notification", lambda *a: calls.append(a) or True)
    path = tmp_path / "notify-state.json"
    nt.maybe_notify(snap("WARN"), str(path))  # baseline
    fired = nt.maybe_notify(snap("WARN"), str(path))
    assert fired is False
    assert calls == []


def test_class_change_notifies_with_useful_content(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nt, "send_notification", lambda title, msg: calls.append((title, msg)) or True)
    path = tmp_path / "notify-state.json"
    nt.maybe_notify(snap("OK"), str(path))
    fired = nt.maybe_notify(snap("CRITICAL"), str(path))
    assert fired is True
    assert len(calls) == 1
    title, message = calls[0]
    assert "token-finops" in title
    assert "Claude Code" in message and "OK" in message and "CRITICAL" in message
    assert json.loads(path.read_text())["last_class"] == "CRITICAL"


def test_recovery_from_warn_or_critical_to_ok_notifies(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nt, "send_notification", lambda *a: calls.append(a) or True)
    path = tmp_path / "notify-state.json"
    nt.maybe_notify(snap("CRITICAL"), str(path))
    fired = nt.maybe_notify(snap("OK"), str(path))
    assert fired is True
    _, message = calls[0]
    assert "CRITICAL" in message and "OK" in message


def test_no_binding_constraint_is_its_own_class(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nt, "send_notification", lambda *a: calls.append(a) or True)
    path = tmp_path / "notify-state.json"
    nt.maybe_notify(snap("WARN"), str(path))
    fired = nt.maybe_notify(snap(None), str(path))
    assert fired is True
    assert json.loads(path.read_text())["last_class"] is None


def test_state_always_updated_even_when_notification_mechanism_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "send_notification", lambda *a: False)
    path = tmp_path / "notify-state.json"
    nt.maybe_notify(snap("OK"), str(path))
    fired = nt.maybe_notify(snap("WARN"), str(path))
    assert fired is False  # mechanism unavailable, no crash
    assert json.loads(path.read_text())["last_class"] == "WARN"


def test_write_state_failure_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "send_notification", lambda *a: True)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(nt, "write_state", boom)
    # must not raise even though persisting the new state failed
    nt.maybe_notify(snap("OK"), str(tmp_path / "notify-state.json"))


# --------------------------------------------------------------------------- #
# platform dispatch and graceful degradation
# --------------------------------------------------------------------------- #
def test_macos_prefers_terminal_notifier_when_present(monkeypatch):
    calls = []
    monkeypatch.setattr(nt.shutil, "which", lambda name: "/usr/local/bin/terminal-notifier" if name == "terminal-notifier" else None)
    monkeypatch.setattr(nt, "_run", lambda cmd: calls.append(cmd))
    assert nt._notify_macos("t", "m") is True
    assert calls[0][0] == "terminal-notifier"


def test_macos_falls_back_to_osascript(monkeypatch):
    calls = []
    monkeypatch.setattr(nt.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None)
    monkeypatch.setattr(nt, "_run", lambda cmd: calls.append(cmd))
    assert nt._notify_macos("t", "m") is True
    assert calls[0][0] == "osascript"


def test_macos_no_mechanism_available_is_noop(monkeypatch):
    monkeypatch.setattr(nt.shutil, "which", lambda name: None)
    assert nt._notify_macos("t", "m") is False


def test_linux_notify_send_missing_is_noop(monkeypatch):
    monkeypatch.setattr(nt.shutil, "which", lambda name: None)
    assert nt._notify_linux("t", "m") is False


def test_linux_notify_send_present_is_used(monkeypatch):
    calls = []
    monkeypatch.setattr(nt.shutil, "which", lambda name: "/usr/bin/notify-send" if name == "notify-send" else None)
    monkeypatch.setattr(nt, "_run", lambda cmd: calls.append(cmd))
    assert nt._notify_linux("t", "m") is True
    assert calls[0][0] == "notify-send"


def test_windows_no_powershell_is_noop(monkeypatch):
    monkeypatch.setattr(nt.shutil, "which", lambda name: None)
    assert nt._notify_windows("t", "m") is False


def test_windows_falls_back_to_balloon_tip_when_burnttoast_missing(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if "BurntToast" in cmd[-1]:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(nt.shutil, "which", lambda name: "powershell.exe" if name == "powershell" else None)
    monkeypatch.setattr(nt, "_run", fake_run)
    assert nt._notify_windows("t", "m") is True
    assert len(calls) == 2
    assert "BurntToast" in calls[0][-1]
    assert "NotifyIcon" in calls[1][-1]


def test_send_notification_never_raises_on_subprocess_failure(monkeypatch):
    monkeypatch.setattr(nt.platform, "system", lambda: "Darwin")

    def boom(title, message):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=5)

    monkeypatch.setattr(nt, "_notify_macos", boom)
    assert nt.send_notification("t", "m") is False


def test_send_notification_unknown_platform_is_noop(monkeypatch):
    monkeypatch.setattr(nt.platform, "system", lambda: "Plan9")
    assert nt.send_notification("t", "m") is False


# --------------------------------------------------------------------------- #
# CLI integration
# --------------------------------------------------------------------------- #
def test_status_notify_flag_never_pops_a_real_notification_and_status_output_unaffected(
    home, run_cli, tmp_path, monkeypatch
):
    from token_finops_cli.adapters.copilot import build_synthetic_db

    calls = []
    monkeypatch.setattr(nt, "send_notification", lambda *a: calls.append(a) or True)
    db = tmp_path / "s.db"
    build_synthetic_db(str(db), days=5, events_per_day=3)
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    cache = tmp_path / "cache.json"
    state = tmp_path / "notify-state.json"

    out_plain = run_cli("status", "--fresh", "--budget", "5000", "--cache-file", str(cache))
    out_notify = run_cli(
        "status", "--fresh", "--budget", "5000", "--cache-file", str(cache),
        "--notify", "--notify-state-file", str(state),
    )
    assert out_plain == out_notify  # --notify never changes stdout
    assert state.exists()
    assert calls == []  # first run only establishes a baseline


def test_status_without_notify_flag_never_touches_state_file(home, run_cli, tmp_path, monkeypatch):
    from token_finops_cli.adapters.copilot import build_synthetic_db

    db = tmp_path / "s.db"
    build_synthetic_db(str(db), days=5, events_per_day=3)
    monkeypatch.setenv("TOKEN_FINOPS_COPILOT_DB", str(db))
    cache = tmp_path / "cache.json"
    state = tmp_path / "notify-state.json"
    run_cli("status", "--fresh", "--budget", "5000", "--cache-file", str(cache))
    assert not state.exists()
