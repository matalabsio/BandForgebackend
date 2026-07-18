"""Tests for writing LLM provider factory."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.writing.providers.constants import PROVIDER_NAME_ANTHROPIC_CLAUDE, PROVIDER_NAME_GROQ
from app.writing.providers.factory import evaluate_writing_essay, writing_eval_configured

VALID_ESSAY = " ".join(["word"] * 40)

VALID_EVAL_JSON = {
    "overall_band": 6.5,
    "task_achievement": 6.0,
    "coherence": 6.5,
    "lexical_resource": 7.0,
    "grammar": 6.0,
    "strengths": ["Clear overview"],
    "weaknesses": ["Limited comparison language"],
    "improvement_tips": ["Use more complex structures"],
    "spelling_mistakes": [],
    "grammar_mistakes": [],
    "spelling_error_count": 0,
}


@contextmanager
def _ops_patches(*, settings_extra: dict | None = None):
    with (
        patch("app.writing.providers.factory.check_claude_budget") as budget,
        patch("app.writing.providers.factory.is_claude_circuit_open") as circuit,
        patch("app.writing.providers.factory.consume_claude_eval"),
        patch("app.writing.providers.factory.record_eval_outcome"),
        patch("app.writing.providers.factory.record_claude_success"),
        patch("app.writing.providers.factory.record_claude_failure"),
        patch("app.writing.providers.factory.record_failure"),
        patch("app.writing.providers.factory.log_writing_eval_request"),
        patch("app.writing.providers.factory.get_settings") as settings,
    ):
        settings.return_value.writing_eval_stub = False
        settings.return_value.ai_budget_fallback_stub = False
        settings.return_value.writing_llm_primary = "claude"
        settings.return_value.writing_llm_fallback = "groq"
        settings.return_value.anthropic_model = "claude-sonnet-4-20250514"
        if settings_extra:
            for key, value in settings_extra.items():
                setattr(settings.return_value, key, value)
        budget.return_value.ok = True
        budget.return_value.reason = None
        circuit.return_value.open = False
        yield settings


def test_writing_eval_configured_when_claude_key_present():
    with (
        patch("app.writing.providers.claude_eval.claude_configured", return_value=True),
        patch("app.writing.providers.groq_eval.groq_configured", return_value=False),
        patch("app.writing.providers.factory.get_settings") as settings,
    ):
        settings.return_value.writing_eval_stub = False
        settings.return_value.ai_budget_fallback_stub = False
        settings.return_value.writing_llm_primary = "claude"
        settings.return_value.writing_llm_fallback = "groq"
        assert writing_eval_configured() is True


def test_writing_eval_configured_false_when_no_keys():
    with (
        patch("app.writing.providers.claude_eval.claude_configured", return_value=False),
        patch("app.writing.providers.groq_eval.groq_configured", return_value=False),
        patch("app.writing.providers.factory.get_settings") as settings,
    ):
        settings.return_value.writing_eval_stub = False
        settings.return_value.ai_budget_fallback_stub = False
        settings.return_value.writing_llm_primary = "claude"
        settings.return_value.writing_llm_fallback = "groq"
        assert writing_eval_configured() is False


def test_claude_primary_success():
    async def run():
        with (
            _ops_patches(
                settings_extra={
                    "writing_llm_fallback": "none",
                    "anthropic_api_key": "sk-ant-test",
                }
            ),
            patch(
                "app.writing.providers.factory.ClaudeWritingProvider.chat_json",
                new_callable=AsyncMock,
                return_value=(json.dumps(VALID_EVAL_JSON), {"content": []}),
            ),
            patch("app.writing.providers.claude_eval.claude_configured", return_value=True),
        ):
            return await evaluate_writing_essay(
                task_part=2,
                question="Discuss both views.",
                essay=VALID_ESSAY,
            )

    result = asyncio.run(run())
    assert result.provider_used == PROVIDER_NAME_ANTHROPIC_CLAUDE
    assert result.evaluation.overall_band == 6.5


def test_claude_fails_groq_fallback():
    async def run():
        with (
            _ops_patches(
                settings_extra={
                    "anthropic_api_key": "sk-ant-test",
                    "groq_api_key": "gsk-test",
                    "groq_model": "llama-3.3-70b-versatile",
                }
            ),
            patch(
                "app.writing.providers.factory.ClaudeWritingProvider.chat_json",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Claude down"),
            ),
            patch(
                "app.writing.providers.factory.GroqWritingProvider.chat_json",
                new_callable=AsyncMock,
                return_value=(json.dumps(VALID_EVAL_JSON), {"choices": []}),
            ),
            patch("app.writing.providers.claude_eval.claude_configured", return_value=True),
            patch("app.writing.providers.groq_eval.groq_configured", return_value=True),
        ):
            return await evaluate_writing_essay(
                task_part=2,
                question="Discuss both views.",
                essay=VALID_ESSAY,
            )

    result = asyncio.run(run())
    assert result.provider_used == PROVIDER_NAME_GROQ


def test_all_providers_fail_raises():
    async def run():
        with (
            _ops_patches(
                settings_extra={
                    "anthropic_api_key": "sk-ant-test",
                    "groq_api_key": "gsk-test",
                }
            ),
            patch(
                "app.writing.providers.factory.ClaudeWritingProvider.chat_json",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Claude down"),
            ),
            patch(
                "app.writing.providers.factory.GroqWritingProvider.chat_json",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Groq down"),
            ),
            patch("app.writing.providers.claude_eval.claude_configured", return_value=True),
            patch("app.writing.providers.groq_eval.groq_configured", return_value=True),
        ):
            await evaluate_writing_essay(
                task_part=2,
                question="Discuss both views.",
                essay=VALID_ESSAY,
            )

    with pytest.raises(RuntimeError):
        asyncio.run(run())
