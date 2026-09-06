# Cache refresher

All status surfaces read `~/.token-finops/last.json` (written by `token-finops status`).
Refresh it from ONE timer so twenty widgets do not each rescan your transcripts.

**Linux (systemd user timer)**
```bash
mkdir -p ~/.config/systemd/user
cp token-finops-refresh.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now token-finops-refresh.timer
```
Adjust `ExecStart` if `token-finops` is not in `~/.local/bin` (e.g. `uv tool install` puts it there).

**macOS (launchd)**
```bash
cp com.tronicum.token-finops.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.tronicum.token-finops.refresh.plist
```

**Anything else**: `*/2 * * * * token-finops status --fresh >/dev/null` in cron.

Widgets then call `token-finops status --format <fmt> --max-age 0` (never rescans) or read
`~/.token-finops/last-line.txt` directly.
