"""Factory for Speaking ASR and evaluation providers."""

from __future__ import annotations

from app.config import get_settings
from app.speaking.providers.base import ASRProvider, EvaluationProvider
from app.speaking.providers.claude_eval import ClaudeEvaluationProvider
from app.speaking.providers.constants import ASRProviderKind, LLMProviderKind
from app.speaking.providers.groq_eval import GroqEvaluationProvider
from app.speaking.providers.groq_whisper import GroqWhisperProvider
from app.speaking.providers.openai_whisper import OpenAIWhisperProvider

_SUPPORTED_ASR = ", ".join(k.value for k in ASRProviderKind)
_SUPPORTED_LLM = ", ".join(k.value for k in LLMProviderKind)


def _parse_asr_kind(raw: str) -> ASRProviderKind:
    normalized = (raw or ASRProviderKind.OPENAI.value).strip().lower()
    try:
        return ASRProviderKind(normalized)
    except ValueError:
        raise ValueError(
            f'Unknown ASR provider: "{raw}".\n'
            f"Supported values: {_SUPPORTED_ASR}."
        ) from None


def _parse_llm_kind(raw: str) -> LLMProviderKind:
    normalized = (raw or LLMProviderKind.CLAUDE.value).strip().lower()
    try:
        return LLMProviderKind(normalized)
    except ValueError:
        raise ValueError(
            f'Unknown LLM provider: "{raw}".\n'
            f"Supported values: {_SUPPORTED_LLM}."
        ) from None


def get_asr_provider() -> ASRProvider:
    kind = _parse_asr_kind(get_settings().asr_provider)
    match kind:
        case ASRProviderKind.OPENAI:
            return OpenAIWhisperProvider()
        case ASRProviderKind.GROQ:
            return GroqWhisperProvider()
    raise ValueError(
        f'Unknown ASR provider: "{kind}".\n'
        f"Supported values: {_SUPPORTED_ASR}."
    )


def get_eval_provider() -> EvaluationProvider:
    kind = _parse_llm_kind(get_settings().llm_provider)
    match kind:
        case LLMProviderKind.CLAUDE:
            return ClaudeEvaluationProvider()
        case LLMProviderKind.GROQ:
            return GroqEvaluationProvider()
    raise ValueError(
        f'Unknown LLM provider: "{kind}".\n'
        f"Supported values: {_SUPPORTED_LLM}."
    )


def get_eval_provider_chain() -> list[EvaluationProvider]:
    """Configured primary followed by a distinct configured fallback."""
    settings = get_settings()
    kinds = [
        _parse_llm_kind(settings.llm_provider),
        _parse_llm_kind(settings.speaking_llm_fallback),
    ]
    providers: list[EvaluationProvider] = []
    for kind in dict.fromkeys(kinds):
        provider: EvaluationProvider
        match kind:
            case LLMProviderKind.CLAUDE:
                provider = ClaudeEvaluationProvider()
            case LLMProviderKind.GROQ:
                provider = GroqEvaluationProvider()
        if provider.configured():
            providers.append(provider)
    return providers


def asr_configured() -> bool:
    return get_asr_provider().configured()


def eval_configured() -> bool:
    return get_eval_provider().configured()
