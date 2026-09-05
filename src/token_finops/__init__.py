"""token-finops: read-only, local-first token usage and budget-runway tracker
for AI coding agents (Copilot CLI, Claude Code, Codex CLI, Gemini CLI, Hermes
Agent, ...) plus a local-vs-cloud savings estimator.

Everything is stdlib-only and never writes to any tool's own data store.
"""

__version__ = "0.1.0"

from .cli import main  # noqa: E402,F401
