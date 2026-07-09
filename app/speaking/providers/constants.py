"""Speaking evaluation provider identifiers."""

from __future__ import annotations

from enum import StrEnum


class ASRProviderKind(StrEnum):
    OPENAI = "openai"
    GROQ = "groq"


class LLMProviderKind(StrEnum):
    CLAUDE = "claude"
    GROQ = "groq"


PROVIDER_NAME_OPENAI_WHISPER = "openai_whisper"
PROVIDER_NAME_GROQ_WHISPER = "groq_whisper"
PROVIDER_NAME_ANTHROPIC_CLAUDE = "anthropic_claude"
PROVIDER_NAME_GROQ = "groq"
PROVIDER_NAME_STUB = "stub"

PROVIDER_VERSION = 1
