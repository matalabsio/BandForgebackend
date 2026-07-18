"""Stub-mode writing evaluator tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.diagnostic.evaluation_schemas import build_stub_evaluation
from app.writing.ai_evaluator import ai_evaluation_available, evaluate_mock_essay
from app.writing.providers.constants import PROVIDER_NAME_STUB
from app.writing.providers.factory import evaluate_writing_essay, writing_eval_configured

VALID_ESSAY = " ".join(["word"] * 40)
SAMPLE_QUESTION = "Discuss both views and give your own opinion."


def test_build_stub_evaluation_validates():
    ev = build_stub_evaluation(task_part=2, essay=VALID_ESSAY)
    assert ev.overall_band == 6.0
    assert len(ev.strengths) >= 1
    assert len(ev.spelling_mistakes) >= 1
    assert len(ev.grammar_mistakes) >= 1
    assert ev.next_band_advice
    assert 0.0 <= ev.confidence <= 1.0
    assert len(ev.vocabulary_highlights) >= 1
    assert len(ev.strong_spans) >= 1


def test_stub_evaluation_to_ai_scores_includes_v5():
    from app.diagnostic.evaluation_schemas import evaluation_to_ai_scores

    ev = build_stub_evaluation(task_part=2, essay=VALID_ESSAY)
    scores = evaluation_to_ai_scores(ev, model_name="stub", provider_used="stub")
    assert "next_band_advice" in scores
    assert "confidence" in scores
    assert scores["vocabulary_highlights"]
    assert scores["strong_spans"]


def test_writing_eval_configured_true_when_stub():
    with patch("app.writing.providers.factory.get_settings") as settings:
        settings.return_value.writing_eval_stub = True
        assert writing_eval_configured() is True


def test_ai_evaluation_available_when_stub():
    with patch("app.writing.ai_evaluator.get_settings") as settings:
        settings.return_value.writing_eval_stub = True
        assert ai_evaluation_available() is True


def test_evaluate_writing_essay_stub_never_calls_claude_or_groq():
    with patch("app.writing.providers.factory.get_settings") as settings, patch(
        "app.writing.providers.stub_eval.WRITING_STUB_DELAY_SEC",
        0,
    ), patch(
        "app.writing.providers.claude_eval.ClaudeWritingProvider.chat_json",
        new_callable=AsyncMock,
    ) as claude_chat, patch(
        "app.writing.providers.groq_eval.GroqWritingProvider.chat_json",
        new_callable=AsyncMock,
    ) as groq_chat:
        settings.return_value.writing_eval_stub = True
        settings.return_value.writing_llm_primary = "claude"
        settings.return_value.writing_llm_fallback = "groq"

        result = asyncio.run(
            evaluate_writing_essay(
                task_part=2,
                question=SAMPLE_QUESTION,
                essay=VALID_ESSAY,
            )
        )

        assert result.provider_used == PROVIDER_NAME_STUB
        assert result.model_name == PROVIDER_NAME_STUB
        assert result.evaluation.overall_band == 6.0
        claude_chat.assert_not_called()
        groq_chat.assert_not_called()


def test_evaluate_mock_essay_stub_cache_hit_skips_provider():
    cached_row = {
        "id": "cached-mock",
        "overall_band": 6.5,
        "criteria_scores": {
            "task_achievement": 6.5,
            "coherence": 6.5,
            "lexical_resource": 6.5,
            "grammar": 6.5,
        },
        "feedback": {
            "strengths": ["Clear overview"],
            "weaknesses": ["Limited range"],
            "improvement_tips": ["Add examples"],
            "spelling_mistakes": [],
            "grammar_mistakes": [],
            "spelling_error_count": 0,
        },
        "model_name": "stub",
        "evaluation_source": "ai_stub",
        "raw_ai_response": {"provider_used": "stub"},
    }

    with patch("app.writing.ai_evaluator.get_settings") as settings, patch(
        "app.writing.ai_evaluator.ai_evaluation_available",
        return_value=True,
    ), patch(
        "app.writing.ai_evaluator.lookup_cached_evaluation",
        return_value=cached_row,
    ), patch(
        "app.writing.ai_evaluator.evaluate_writing_essay",
        new_callable=AsyncMock,
    ) as evaluate, patch(
        "app.writing.ai_evaluator.persist_evaluation",
    ) as persist:
        settings.return_value.writing_eval_stub = True
        result = asyncio.run(
            evaluate_mock_essay(
                part=2,
                question=SAMPLE_QUESTION,
                essay=VALID_ESSAY,
            )
        )
        evaluate.assert_not_called()
        persist.assert_not_called()
        assert result is not None
        assert result["ai_band"] == 6.5
        assert result["provider_used"] == "stub"


def test_evaluate_mock_essay_stub_persists_ai_stub_source():
    with patch("app.writing.ai_evaluator.get_settings") as settings, patch(
        "app.writing.ai_evaluator.lookup_cached_evaluation",
        return_value=None,
    ), patch(
        "app.writing.ai_evaluator.evaluate_writing_essay",
        new_callable=AsyncMock,
    ) as evaluate, patch(
        "app.writing.ai_evaluator.persist_evaluation",
    ) as persist, patch(
        "app.writing.providers.stub_eval.WRITING_STUB_DELAY_SEC",
        0,
    ):
        settings.return_value.writing_eval_stub = True
        mock_result = MagicMock()
        mock_result.evaluation = build_stub_evaluation(task_part=2, essay=VALID_ESSAY)
        mock_result.raw_store = {"provider_used": "stub"}
        mock_result.prompt_version = "v4"
        mock_result.model_name = "stub"
        mock_result.provider_used = "stub"
        evaluate.return_value = mock_result

        result = asyncio.run(
            evaluate_mock_essay(
                part=2,
                question=SAMPLE_QUESTION,
                essay=VALID_ESSAY,
            )
        )

        assert result is not None
        persist.assert_called_once()
        assert persist.call_args.kwargs["evaluation_source"] == "ai_stub"
