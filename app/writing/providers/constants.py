"""Writing evaluation provider identifiers."""

from __future__ import annotations

from enum import StrEnum


class WritingLLMProviderKind(StrEnum):
    CLAUDE = "claude"
    GROQ = "groq"
    NONE = "none"


PROVIDER_NAME_ANTHROPIC_CLAUDE = "anthropic_claude"
PROVIDER_NAME_GROQ = "groq"
PROVIDER_NAME_STUB = "stub"

WRITING_EVAL_MAX_TOKENS_CLAUDE = 1500
WRITING_STUB_DELAY_SEC = 2.0
