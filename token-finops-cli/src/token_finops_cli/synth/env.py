"""Environment variables that redirect every adapter at one fake home
directory, for `token-finops synth --print-env` / `eval "$(...)"`.

Every adapter already exposes an env override for its data root (see each
adapter's docstring) -- none needed a new one added. `env_for()` just points
all of them, plus `HOME`, at the same `out_dir` that `synth.generate()` wrote:

    TOKEN_FINOPS_COPILOT_DB   Copilot session-store.db          (adapters/copilot.py)
    CLAUDE_CONFIG_DIR         Claude Code ~/.claude              (adapters/claude_code.py)
    CODEX_HOME                Codex CLI ~/.codex                 (adapters/codex.py)
    GEMINI_CLI_HOME           Gemini CLI ~/.gemini                (adapters/gemini_cli.py)
    HERMES_HOME               Hermes Agent ~/.hermes              (adapters/hermes.py)
    XDG_DATA_HOME             OpenCode's ~/.local/share default   (adapters/opencode.py)
    TOKEN_FINOPS_OPENCODE_DB  OpenCode/Kilo db path(s), explicit  (adapters/opencode.py)
    TOKEN_FINOPS_CLINE_DIRS   Cline/Roo/Kilo VS Code globalStorage roots (adapters/cline.py)
    TOKEN_FINOPS_AIDER_DIRS   Aider chat-history search roots      (adapters/aider.py)
    CONTINUE_GLOBAL_DIR       Continue.dev ~/.continue            (adapters/continue_dev.py)

`HOME`/`USERPROFILE` are set too so anything that falls back to `~` (Aider's
default search root is literally `~`) still resolves under `out_dir` even
without its own override.

Caveat: `adapters.claude_code` reads `QUOTA_FILE`/`QUOTA_HISTORY_FILE` as
module-level constants computed from `HOME` *at import time*. Setting these
env vars and then running `token-finops` as a fresh process (the `eval
"$(token-finops synth --print-env)" && token-finops report` one-liner) picks
them up correctly. Reusing them inside an already-running process (as
tests do) requires also monkeypatching `claude_code.QUOTA_FILE` /
`claude_code.QUOTA_HISTORY_FILE`, exactly as `tests/conftest.py`'s `home`
fixture already does.
"""
from __future__ import annotations

import os


def env_for(out_dir: str) -> dict[str, str]:
    out_dir = os.path.abspath(out_dir)
    return {
        "HOME": out_dir,
        "USERPROFILE": out_dir,
        "TOKEN_FINOPS_COPILOT_DB": os.path.join(out_dir, ".copilot", "session-store.db"),
        "CLAUDE_CONFIG_DIR": os.path.join(out_dir, ".claude"),
        "CODEX_HOME": os.path.join(out_dir, ".codex"),
        "GEMINI_CLI_HOME": os.path.join(out_dir, ".gemini"),
        "HERMES_HOME": os.path.join(out_dir, ".hermes"),
        "XDG_DATA_HOME": os.path.join(out_dir, ".local", "share"),
        "TOKEN_FINOPS_OPENCODE_DB": os.path.join(out_dir, ".local", "share", "opencode", "opencode.db"),
        "TOKEN_FINOPS_CLINE_DIRS": os.path.join(out_dir, ".config", "Code", "User", "globalStorage"),
        "CONTINUE_GLOBAL_DIR": os.path.join(out_dir, ".continue"),
        "TOKEN_FINOPS_AIDER_DIRS": out_dir,
    }
