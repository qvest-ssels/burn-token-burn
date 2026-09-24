"""`token-finops status --notify` — a desktop notification when the binding
constraint's status class changes (T-11, `claude-tasks.md`).

Only the *class transition* matters (OK -> WARN, WARN -> CRITICAL, and just as
importantly WARN/CRITICAL -> OK so a user learns they are back in the clear) —
never fire on every run while the class is unchanged, or this becomes the kind
of tool people disable. State lives in `~/.token-finops/notify-state.json`,
next to `last.json` and `config.json`.

Platform mechanisms, in the order each is tried:

- **macOS**: `terminal-notifier` if installed, else `osascript -e 'display
  notification ...'` -- the latter ships with every macOS install, so there is
  always a working path. Verified on this machine (Darwin, no
  `terminal-notifier` installed -> falls through to `osascript`).
- **Linux**: `notify-send` (part of `libnotify-bin` / `libnotify`, standard on
  GNOME/KDE/most desktop distros). **Unverified** -- no Linux desktop
  environment available in this environment to test against; only the
  presence check (`shutil.which`) and command shape were exercised.
- **Windows**: PowerShell's `New-BurntToastNotification` if the (third-party,
  not preinstalled) BurntToast module happens to be present, else a
  `System.Windows.Forms.NotifyIcon` balloon tip, which needs no module beyond
  the .NET Framework that ships with Windows. **Best-effort and unverified**
  -- there is no Windows machine in this environment; the command strings
  were written from documented PowerShell/.NET APIs but never executed.

Every mechanism above is wrapped so a missing binary, a non-zero exit, a
timeout, or any other `OSError`/`subprocess` failure degrades to a silent
no-op (at most a note on stderr) -- `status`'s stdout and exit code must never
depend on whether desktop notifications work on this machine.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from typing import Optional

STATE_DIR = os.path.expanduser("~/.token-finops")
STATE_FILE = os.path.join(STATE_DIR, "notify-state.json")

_TIMEOUT = 5


# --------------------------------------------------------------------------- #
# state file
# --------------------------------------------------------------------------- #
def read_state(path: str = STATE_FILE) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_state(state: dict, path: str = STATE_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# platform mechanisms
# --------------------------------------------------------------------------- #
def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT, check=True)


def _osa_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _notify_macos(title: str, message: str) -> bool:
    if shutil.which("terminal-notifier"):
        _run(["terminal-notifier", "-title", title, "-message", message])
        return True
    if shutil.which("osascript"):
        script = f"display notification {_osa_quote(message)} with title {_osa_quote(title)}"
        _run(["osascript", "-e", script])
        return True
    return False


def _notify_linux(title: str, message: str) -> bool:
    if not shutil.which("notify-send"):
        return False
    _run(["notify-send", title, message])
    return True


def _notify_windows(title: str, message: str) -> bool:
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return False
    burnt_toast = (
        "Import-Module BurntToast -ErrorAction Stop; "
        f"New-BurntToastNotification -Text {_ps_quote(title)}, {_ps_quote(message)}"
    )
    try:
        _run([ps, "-NoProfile", "-NonInteractive", "-Command", burnt_toast])
        return True
    except (subprocess.SubprocessError, OSError):
        pass
    # No third-party module required, but genuinely never exercised on Windows.
    balloon = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Information; "
        "$n.Visible = $true; "
        f"$n.ShowBalloonTip(5000, {_ps_quote(title)}, {_ps_quote(message)}, "
        "[System.Windows.Forms.ToolTipIcon]::Info); "
        "Start-Sleep -Milliseconds 500; "
        "$n.Dispose()"
    )
    try:
        _run([ps, "-NoProfile", "-NonInteractive", "-Command", balloon])
        return True
    except (subprocess.SubprocessError, OSError):
        return False


_DISPATCH_NAMES = {"Darwin": "_notify_macos", "Linux": "_notify_linux", "Windows": "_notify_windows"}


def send_notification(title: str, message: str) -> bool:
    """Best-effort desktop notification. Never raises -- returns whether one
    actually fired, and notes the reason on stderr when it did not."""
    name = _DISPATCH_NAMES.get(platform.system())
    if name is None:
        return False
    fn = globals()[name]
    try:
        return fn(title, message)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"token-finops: --notify: desktop notification unavailable ({exc})", file=sys.stderr)
        return False


# --------------------------------------------------------------------------- #
# class-change diff
# --------------------------------------------------------------------------- #
def maybe_notify(snapshot: dict, state_path: str = STATE_FILE) -> bool:
    """Compare the binding constraint's status class against the last run's
    recorded class and fire a notification only on an actual change. Always
    rewrites the state file afterward, first-run or not, notified or not, so
    the next run has an accurate baseline. Returns whether a notification
    actually fired (mostly useful for tests)."""
    binding = snapshot.get("binding")
    current_class = binding.get("status") if binding else None
    tool_name = (binding or {}).get("display_name") or (binding or {}).get("tool")

    prior = read_state(state_path)
    prior_class = prior.get("last_class") if prior else None

    fired = False
    if prior is not None and current_class != prior_class:
        title = "token-finops"
        if current_class is None:
            message = f"{prior.get('tool_display') or prior.get('tool') or 'binding constraint'}: back to no binding constraint"
        elif prior_class is None:
            message = f"{tool_name}: now {current_class}"
        else:
            message = f"{tool_name}: {prior_class} -> {current_class}"
        fired = send_notification(title, message)

    new_state = {
        "last_class": current_class,
        "tool": (binding or {}).get("tool"),
        "tool_display": (binding or {}).get("display_name"),
        "updated_at": snapshot.get("generated_at"),
    }
    try:
        write_state(new_state, state_path)
    except OSError:
        pass
    return fired
