"""Claude provider for writing evaluation (roadmap: ClaudeProvider).

Uses the shared Anthropic Messages client with writing-specific timeout / max_tokens.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.writing.providers.claude_client import chat_completion_json, claude_configured
from app.writing.providers.constants import (
    PROVIDER_NAME_ANTHROPIC_CLAUDE,
    WRITING_EVAL_MAX_TOKENS_CLAUDE,
)


class ClaudeWritingProvider:
    """ClaudeProvider — writing evaluation LLM via Anthropic Messages API."""

    name = PROVIDER_NAME_ANTHROPIC_CLAUDE

    @property
    def model(self) -> str:
        return get_settings().anthropic_model

    def configured(self) -> bool:
        return claude_configured()

    async def chat_json(self, *, system: str, user: str) -> tuple[str, dict[str, Any]]:
        settings = get_settings()
        return await chat_completion_json(
            system=system,
            user=user,
            model=self.model,
            max_tokens=WRITING_EVAL_MAX_TOKENS_CLAUDE,
            timeout=float(settings.writing_eval_timeout_sec),
        )


# Roadmap deliverable name
ClaudeProvider = ClaudeWritingProvider
