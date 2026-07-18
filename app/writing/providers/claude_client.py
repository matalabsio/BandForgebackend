"""Writing-facing Claude client surface (re-exports shared Speaking client).

Roadmap deliverable: ClaudeClient — keep a single HTTP implementation in
app.speaking.claude_client; this module is the writing import path.
"""

from __future__ import annotations

from app.speaking.claude_client import (
    chat_completion_json,
    claude_configuration_error,
    claude_configured,
    resolve_claude_auth_mode,
)

__all__ = [
    "chat_completion_json",
    "claude_configuration_error",
    "claude_configured",
    "resolve_claude_auth_mode",
]
