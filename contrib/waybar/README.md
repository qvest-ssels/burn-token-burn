# waybar / polybar / i3blocks

**waybar** (`~/.config/waybar/config`):
```json
"custom/token-finops": {
  "exec": "token-finops status --format waybar --max-age 0",
  "return-type": "json",
  "interval": 60,
  "format": "  {}",
  "tooltip": true
}
```
CSS classes: `.ok`, `.warn`, `.critical`, `.exhausted`, `.unknown`.

**polybar**: `exec = token-finops status --format polybar --max-age 0`, `interval = 60`.

**i3blocks**: `command=token-finops status --format i3 --max-age 0` (prints text, short text, colour).
