"""Speaking provider factory tests."""

from unittest.mock import MagicMock, patch

import pytest

from app.speaking.providers.constants import (
    PROVIDER_NAME_ANTHROPIC_CLAUDE,
    PROVIDER_NAME_GROQ,
    PROVIDER_NAME_GROQ_WHISPER,
    PROVIDER_NAME_OPENAI_WHISPER,
)
from app.speaking.providers.factory import (
    get_asr_provider,
    get_eval_provider,
)
from app.speaking.providers.groq_eval import GroqEvaluationProvider
from app.speaking.providers.groq_whisper import GroqWhisperProvider
from app.speaking.providers.openai_whisper import OpenAIWhisperProvider
from app.speaking.providers.claude_eval import ClaudeEvaluationProvider


def test_get_asr_provider_openai():
    with patch("app.speaking.providers.factory.get_settings") as mock_settings:
        mock_settings.return_value.asr_provider = "openai"
        provider = get_asr_provider()
    assert isinstance(provider, OpenAIWhisperProvider)
    assert provider.name == PROVIDER_NAME_OPENAI_WHISPER


def test_get_asr_provider_groq():
    with patch("app.speaking.providers.factory.get_settings") as mock_settings:
        mock_settings.return_value.asr_provider = "groq"
        provider = get_asr_provider()
    assert isinstance(provider, GroqWhisperProvider)
    assert provider.name == PROVIDER_NAME_GROQ_WHISPER


def test_get_eval_provider_claude():
    with patch("app.speaking.providers.factory.get_settings") as mock_settings:
        mock_settings.return_value.llm_provider = "claude"
        provider = get_eval_provider()
    assert isinstance(provider, ClaudeEvaluationProvider)
    assert provider.name == PROVIDER_NAME_ANTHROPIC_CLAUDE


def test_get_eval_provider_groq():
    with patch("app.speaking.providers.factory.get_settings") as mock_settings:
        mock_settings.return_value.llm_provider = "groq"
        provider = get_eval_provider()
    assert isinstance(provider, GroqEvaluationProvider)
    assert provider.name == PROVIDER_NAME_GROQ


def test_unknown_asr_provider_raises():
    with patch("app.speaking.providers.factory.get_settings") as mock_settings:
        mock_settings.return_value.asr_provider = "xyz"
        with pytest.raises(ValueError, match="Unknown ASR provider"):
            get_asr_provider()


def test_unknown_llm_provider_raises():
    with patch("app.speaking.providers.factory.get_settings") as mock_settings:
        mock_settings.return_value.llm_provider = "xyz"
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_eval_provider()


def test_asr_provider_configured_checks_openai_key():
    provider = OpenAIWhisperProvider()
    with patch(
        "app.speaking.providers.openai_whisper.whisper_configured",
        return_value=True,
    ):
        assert provider.configured() is True


def test_groq_asr_provider_configured_checks_groq_key():
    provider = GroqWhisperProvider()
    with patch(
        "app.speaking.providers.groq_whisper.groq_configured",
        return_value=True,
    ):
        assert provider.configured() is True
