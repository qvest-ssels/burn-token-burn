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

Both units also chain `token-finops burn --record --since 7d` after the status refresh, so
`~/.token-finops/history.jsonl` stays current without a second timer — `burn --by month
--history` then has today's numbers without you remembering to run `--record` by hand. `--since
7d` is enough since `--record` upserts by `(tool, day)`; a wider window just re-writes days that
were already recorded.
