"""Tests for diagnostic AI writing evaluation."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.diagnostic.evaluation_schemas import (
    DiagnosticEvaluateWritingResponse,
    EvaluationResponse,
    compute_overall_band_from_criteria,
    length_warnings,
    reconcile_overall_band,
    row_to_public_response,
)
from app.diagnostic.rate_limit import _buckets, check_evaluate_writing_rate_limit
from app.diagnostic.writing_evaluator import (
    _is_cache_valid,
    compute_essay_hash,
    evaluate_diagnostic_writing,
)
from app.main import app

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
    "spelling_mistakes": [
        {"original": "goverment", "correction": "government", "context": "The goverment"},
    ],
    "grammar_mistakes": [],
    "spelling_error_count": 1,
}


def test_evaluation_response_validates_and_rounds_bands():
    ev = EvaluationResponse.model_validate(VALID_EVAL_JSON)
    assert ev.overall_band == 6.5
    assert ev.task_achievement == 6.0


def test_evaluation_response_clamps_out_of_range_band():
    ev = EvaluationResponse.model_validate({**VALID_EVAL_JSON, "overall_band": 10.0})
    assert ev.overall_band == 9.0


def test_evaluation_response_rejects_missing_fields():
    with pytest.raises(ValidationError):
        EvaluationResponse.model_validate({"overall_band": 6.0})


def test_evaluation_response_rounds_to_half_steps():
    ev = EvaluationResponse.model_validate({**VALID_EVAL_JSON, "grammar": 6.3})
    assert ev.grammar == 6.5


def test_row_to_public_response_excludes_evaluation_source():
    row = {
        "id": "eval-uuid",
        "overall_band": 6.5,
        "criteria_scores": {
            "task_achievement": 6.0,
            "coherence": 6.5,
            "lexical_resource": 7.0,
            "grammar": 6.0,
        },
        "feedback": {
            "strengths": ["Clear overview"],
            "weaknesses": ["Limited comparison language"],
            "improvement_tips": ["Use more complex structures"],
        },
        "word_count": 200,
        "task_part": 1,
        "sentence_count": 10,
        "paragraph_count": 3,
        "evaluation_source": "ai",
    }
    public = row_to_public_response(row)
    dumped = public.model_dump()
    assert "evaluation_source" not in dumped
    assert dumped["writing_band"] == 6.5
    assert dumped["warnings"] == []


def test_length_warning_when_below_ielts_minimum():
    assert length_warnings(task_part=1, word_count=40) != []
    assert length_warnings(task_part=1, word_count=160) == []


def test_row_to_public_response_includes_length_warning():
    row = {
        "id": "short-uuid",
        "overall_band": 4.5,
        "task_part": 1,
        "criteria_scores": {
            "task_achievement": 4.5,
            "coherence": 4.5,
            "lexical_resource": 4.5,
            "grammar": 4.5,
        },
        "feedback": {
            "strengths": ["Attempted"],
            "weaknesses": ["Too short"],
            "improvement_tips": ["Write more"],
        },
        "word_count": 40,
        "sentence_count": 3,
        "paragraph_count": 1,
    }
    public = row_to_public_response(row)
    assert len(public.warnings) == 1
    assert "150 words" in public.warnings[0]


def test_prompt_version_is_v5():
    from app.diagnostic.writing_prompt import PROMPT_VERSION, SYSTEM_PROMPT

    assert PROMPT_VERSION == "v5"
    assert "Be conservative when scoring" in SYSTEM_PROMPT
    assert "spelling_mistakes" in SYSTEM_PROMPT
    assert "next_band_advice" in SYSTEM_PROMPT
    assert "vocabulary_highlights" in SYSTEM_PROMPT
    assert "approximately the average of" in SYSTEM_PROMPT


def test_evaluation_response_defaults_v5_fields_for_legacy_payload():
    ev = EvaluationResponse.model_validate(VALID_EVAL_JSON)
    assert ev.next_band_advice == ""
    assert ev.confidence == 0.5
    assert ev.vocabulary_highlights == []
    assert ev.strong_spans == []


def test_evaluation_response_accepts_v5_fields():
    ev = EvaluationResponse.model_validate(
        {
            **VALID_EVAL_JSON,
            "next_band_advice": "Add a clearer overview sentence.",
            "confidence": 0.82,
            "vocabulary_highlights": [
                {"word": "good", "polarity": "weak", "alternatives": ["beneficial"]},
                {"word": "crucial", "polarity": "strong", "alternatives": []},
            ],
            "strong_spans": [{"text": "Overall, sales rose", "reason": "Clear overview"}],
        }
    )
    assert ev.next_band_advice.startswith("Add a clearer")
    assert ev.confidence == 0.82
    assert len(ev.vocabulary_highlights) == 2
    assert ev.strong_spans[0].text == "Overall, sales rose"


def test_evaluation_response_clamps_confidence():
    ev = EvaluationResponse.model_validate({**VALID_EVAL_JSON, "confidence": 1.5})
    assert ev.confidence == 1.0
    ev2 = EvaluationResponse.model_validate({**VALID_EVAL_JSON, "confidence": -0.2})
    assert ev2.confidence == 0.0


def test_feedback_and_ai_scores_include_v5_fields():
    from app.diagnostic.evaluation_schemas import (
        feedback_from_evaluation,
        evaluation_to_ai_scores,
    )

    ev = EvaluationResponse.model_validate(
        {
            **VALID_EVAL_JSON,
            "next_band_advice": "Compare two countries explicitly.",
            "confidence": 0.7,
            "vocabulary_highlights": [
                {"word": "good", "polarity": "weak", "alternatives": ["useful"]},
            ],
            "strong_spans": [{"text": "In summary", "reason": "Closing"}],
        }
    )
    feedback = feedback_from_evaluation(ev)
    assert feedback["next_band_advice"] == "Compare two countries explicitly."
    assert feedback["confidence"] == 0.7
    assert feedback["vocabulary_highlights"][0]["word"] == "good"
    scores = evaluation_to_ai_scores(ev, model_name="stub", provider_used="stub")
    assert scores["next_band_advice"] == "Compare two countries explicitly."
    assert scores["confidence"] == 0.7
    assert scores["strong_spans"][0]["text"] == "In summary"


def test_coerce_parsed_evaluation_fills_v5_defaults():
    from app.writing.providers.evaluation_call import coerce_parsed_evaluation

    parsed = coerce_parsed_evaluation(dict(VALID_EVAL_JSON), words=40, task_part=2)
    assert parsed["next_band_advice"] == ""
    assert parsed["confidence"] == 0.5
    assert parsed["vocabulary_highlights"] == []
    assert parsed["strong_spans"] == []
    EvaluationResponse.model_validate(parsed)


def test_row_to_evaluation_response_tolerates_v4_feedback():
    from app.writing.eval_cache import row_to_evaluation_response

    row = {
        "overall_band": 6.5,
        "criteria_scores": {
            "task_achievement": 6.0,
            "coherence": 6.5,
            "lexical_resource": 7.0,
            "grammar": 6.0,
        },
        "feedback": {
            "strengths": ["Clear overview"],
            "weaknesses": ["Limited comparison language"],
            "improvement_tips": ["Use more complex structures"],
            "spelling_mistakes": [],
            "grammar_mistakes": [],
            "spelling_error_count": 0,
        },
    }
    ev = row_to_evaluation_response(row)
    assert ev is not None
    assert ev.confidence == 0.5
    assert ev.next_band_advice == ""
    assert ev.vocabulary_highlights == []
    assert ev.strong_spans == []


def test_compute_overall_band_from_criteria():
    assert compute_overall_band_from_criteria(6.0, 6.5, 7.0, 6.0) == 6.5


def test_reconcile_overall_band_within_threshold():
    ev = EvaluationResponse.model_validate(
        {
            **VALID_EVAL_JSON,
            "overall_band": 6.5,
            "task_achievement": 6.0,
            "coherence": 5.0,
            "lexical_resource": 6.0,
            "grammar": 7.0,
        },
    )
    reconciled, changed = reconcile_overall_band(ev)
    assert changed is False
    assert reconciled.overall_band == 6.5


def test_reconcile_overall_band_when_drift_exceeds_threshold():
    ev = EvaluationResponse.model_validate(
        {
            **VALID_EVAL_JSON,
            "overall_band": 7.5,
            "task_achievement": 6.0,
            "coherence": 6.0,
            "lexical_resource": 6.0,
            "grammar": 6.0,
        },
    )
    reconciled, changed = reconcile_overall_band(ev)
    assert changed is True
    assert reconciled.overall_band == 6.0


def test_evaluation_response_accepts_spelling_mistakes():
    ev = EvaluationResponse.model_validate(VALID_EVAL_JSON)
    assert len(ev.spelling_mistakes) == 1
    assert ev.spelling_mistakes[0].original == "goverment"
    assert ev.spelling_error_count == 1


def test_provider_reconciles_overall_band_when_drift_exceeds_threshold():
    from app.diagnostic.evaluation_schemas import EvaluationResponse
    from app.writing.providers.evaluation_call import WritingEvaluationResult

    mismatched = {
        **VALID_EVAL_JSON,
        "overall_band": 7.5,
        "task_achievement": 6.0,
        "coherence": 6.0,
        "lexical_resource": 6.0,
        "grammar": 6.0,
    }

    async def run():
        with patch(
            "app.writing.providers.factory.ClaudeWritingProvider.chat_json",
            new_callable=AsyncMock,
            return_value=(json.dumps(mismatched), {"content": []}),
        ), patch(
            "app.writing.providers.claude_eval.claude_configured",
            return_value=True,
        ), patch(
            "app.writing.providers.factory.get_settings"
        ) as settings, patch(
            "app.writing.providers.factory.check_claude_budget"
        ) as budget, patch(
            "app.writing.providers.factory.is_claude_circuit_open"
        ) as circuit, patch(
            "app.writing.providers.factory.consume_claude_eval"
        ), patch(
            "app.writing.providers.factory.record_eval_outcome"
        ), patch(
            "app.writing.providers.factory.record_claude_success"
        ), patch(
            "app.writing.providers.factory.log_writing_eval_request"
        ):
            settings.return_value.writing_eval_stub = False
            settings.return_value.ai_budget_fallback_stub = False
            settings.return_value.writing_llm_primary = "claude"
            settings.return_value.writing_llm_fallback = "none"
            settings.return_value.anthropic_api_key = "test-key"
            settings.return_value.anthropic_model = "claude-sonnet-4-20250514"
            budget.return_value.ok = True
            budget.return_value.reason = None
            circuit.return_value.open = False
            from app.writing.providers.factory import evaluate_writing_essay

            return await evaluate_writing_essay(
                task_part=1,
                question="Chart question",
                essay=VALID_ESSAY,
            )

    result: WritingEvaluationResult = asyncio.run(run())

    assert result.prompt_version == "v5"
    assert result.evaluation.overall_band == 6.0
    assert result.raw_store["overall_band_reconciled"] is True
    assert result.provider_used == "anthropic_claude"


def test_groq_reconciles_overall_band_when_drift_exceeds_threshold():
    from app.writing.providers.evaluation_call import WritingEvaluationResult

    mismatched = {
        **VALID_EVAL_JSON,
        "overall_band": 7.5,
        "task_achievement": 6.0,
        "coherence": 6.0,
        "lexical_resource": 6.0,
        "grammar": 6.0,
    }

    async def run():
        with patch(
            "app.writing.providers.factory.GroqWritingProvider.chat_json",
            new_callable=AsyncMock,
            return_value=(json.dumps(mismatched), {"choices": []}),
        ), patch(
            "app.writing.providers.groq_eval.groq_configured",
            return_value=True,
        ), patch(
            "app.writing.providers.factory.get_settings"
        ) as settings, patch(
            "app.writing.providers.factory.check_claude_budget"
        ) as budget, patch(
            "app.writing.providers.factory.is_claude_circuit_open"
        ) as circuit, patch(
            "app.writing.providers.factory.record_eval_outcome"
        ), patch(
            "app.writing.providers.factory.log_writing_eval_request"
        ):
            settings.return_value.writing_eval_stub = False
            settings.return_value.ai_budget_fallback_stub = False
            settings.return_value.writing_llm_primary = "groq"
            settings.return_value.writing_llm_fallback = "none"
            settings.return_value.groq_api_key = "test-key"
            settings.return_value.groq_model = "llama-3.3-70b-versatile"
            budget.return_value.ok = True
            budget.return_value.reason = None
            circuit.return_value.open = False
            from app.writing.providers.factory import evaluate_writing_essay

            return await evaluate_writing_essay(
                task_part=1,
                question="Chart question",
                essay=VALID_ESSAY,
            )

    result: WritingEvaluationResult = asyncio.run(run())

    assert result.prompt_version == "v5"
    assert result.evaluation.overall_band == 6.0
    assert result.raw_store["overall_band_reconciled"] is True
    assert result.provider_used == "groq"


def test_compute_essay_hash_is_stable():
    h1 = compute_essay_hash(task_part=1, question="Q", essay="Essay text")
    h2 = compute_essay_hash(task_part=1, question="Q", essay="Essay text")
    assert h1 == h2
    assert h1 != compute_essay_hash(task_part=1, question="Q", essay="Different")


def test_essay_hash_cache_hit_skips_groq():
    cached_row = {
        "id": "cached-id",
        "overall_band": 7.0,
        "criteria_scores": {
            "task_achievement": 7.0,
            "coherence": 7.0,
            "lexical_resource": 7.0,
            "grammar": 7.0,
        },
        "feedback": {
            "strengths": ["Good"],
            "weaknesses": ["Weak"],
            "improvement_tips": ["Tip"],
        },
        "word_count": 180,
        "task_part": 1,
        "sentence_count": 8,
        "paragraph_count": 2,
        "evaluation_source": "ai",
        "evaluated_at": datetime.now(UTC).isoformat(),
    }
    request = MagicMock()
    body = MagicMock(
        client_attempt_id="attempt-1",
        task_part=1,
        question="Chart question",
        essay=VALID_ESSAY,
    )

    with patch(
        "app.diagnostic.writing_evaluator._lookup_by_essay_hash",
        return_value=cached_row,
    ), patch(
        "app.diagnostic.writing_evaluator._lookup_by_client_attempt",
        return_value=None,
    ), patch(
        "app.diagnostic.writing_evaluator.evaluate_writing_essay",
        new_callable=AsyncMock,
    ) as evaluate, patch(
        "app.diagnostic.writing_evaluator.record_evaluate_writing_rate_limit"
    ) as rate:
        result = asyncio.run(evaluate_diagnostic_writing(body, request))
        evaluate.assert_not_called()
        rate.assert_not_called()
        assert result.evaluation_id == "cached-id"
        assert result.writing_band == 7.0


def test_rejects_essay_shorter_than_100_words_after_cleaning():
    request = MagicMock()
    body = MagicMock(
        client_attempt_id="attempt-short",
        task_part=1,
        question="Chart question",
        essay="hi my name is divyansh",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(evaluate_diagnostic_writing(body, request))
    assert exc.value.status_code == 400
    assert "too short" in str(exc.value.detail).lower()


def test_fallback_rows_are_never_served_from_cache():
    old = datetime.now(UTC) - timedelta(days=1)
    recent = datetime.now(UTC) - timedelta(minutes=1)
    assert _is_cache_valid(
        {"evaluation_source": "fallback", "evaluated_at": old.isoformat()},
    ) is False
    assert _is_cache_valid(
        {"evaluation_source": "fallback", "evaluated_at": recent.isoformat()},
    ) is False
    assert _is_cache_valid({"evaluation_source": "ai", "evaluated_at": old.isoformat()}) is True
    assert _is_cache_valid({"evaluation_source": "ai_stub", "evaluated_at": old.isoformat()}) is True


def test_sanitize_essay_strips_pasted_instructions():
    from app.diagnostic.writing_evaluator import sanitize_essay

    question = "The bar chart below shows commuter transport."
    essay = (
        "hi i am divyansh You should spend about 20 minutes on this task. "
        "The bar chart below shows commuter transport. "
        "Summarise the information by selecting and reporting the main features. "
        "Write at least 150 words."
    )
    cleaned = sanitize_essay(essay, question)
    assert "You should spend" not in cleaned
    assert "Write at least" not in cleaned
    assert "hi i am divyansh" in cleaned


def test_missing_provider_returns_503():
    request = MagicMock()
    body = MagicMock(
        client_attempt_id="attempt-no-key",
        task_part=1,
        question="Chart question",
        essay=" ".join(["word"] * 160),
    )

    with (
        patch("app.diagnostic.writing_evaluator._lookup_by_essay_hash", return_value=None),
        patch("app.diagnostic.writing_evaluator._lookup_by_client_attempt", return_value=None),
        patch("app.diagnostic.writing_evaluator.record_evaluate_writing_rate_limit"),
        patch("app.diagnostic.writing_evaluator.writing_eval_configured", return_value=False),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(evaluate_diagnostic_writing(body, request))
    assert exc.value.status_code == 503


def test_evaluation_failure_returns_503():
    request = MagicMock()
    body = MagicMock(
        client_attempt_id="attempt-groq-fail",
        task_part=1,
        question="Chart question",
        essay=VALID_ESSAY,
    )

    with (
        patch("app.diagnostic.writing_evaluator._lookup_by_essay_hash", return_value=None),
        patch("app.diagnostic.writing_evaluator._lookup_by_client_attempt", return_value=None),
        patch("app.diagnostic.writing_evaluator.record_evaluate_writing_rate_limit"),
        patch("app.diagnostic.writing_evaluator.writing_eval_configured", return_value=True),
        patch(
            "app.diagnostic.writing_evaluator.evaluate_writing_essay",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Evaluation failed"),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(evaluate_diagnostic_writing(body, request))
    assert exc.value.status_code == 503


def test_provider_retry_on_invalid_json_then_success():
    from app.diagnostic.evaluation_schemas import EvaluationResponse
    from app.writing.providers.evaluation_call import call_writing_evaluation_with_retry

    calls: list[int] = []

    async def llm_side_effect(_system: str, _user: str):
        calls.append(1)
        if len(calls) == 1:
            return "not-json", {}
        return json.dumps(VALID_EVAL_JSON), {}

    async def run():
        return await call_writing_evaluation_with_retry(
            llm_call=llm_side_effect,
            task_part=1,
            question="Chart question",
            essay=VALID_ESSAY,
            provider_label="test",
            model_name="test-model",
            provider_used="test",
        )

    result = asyncio.run(run())
    assert isinstance(result.evaluation, EvaluationResponse)
    assert len(calls) == 2


def test_groq_retry_on_invalid_json_then_success():
    from app.diagnostic.evaluation_schemas import EvaluationResponse
    from app.writing.providers.evaluation_call import WritingEvaluationResult

    request = MagicMock()
    body = MagicMock(
        client_attempt_id="attempt-retry",
        task_part=1,
        question="Chart question",
        essay=VALID_ESSAY,
    )
    persisted = {
        "id": "retry-id",
        "overall_band": 6.5,
        "criteria_scores": criteria_from_row(VALID_EVAL_JSON),
        "feedback": {
            "strengths": VALID_EVAL_JSON["strengths"],
            "weaknesses": VALID_EVAL_JSON["weaknesses"],
            "improvement_tips": VALID_EVAL_JSON["improvement_tips"],
            "spelling_mistakes": VALID_EVAL_JSON["spelling_mistakes"],
            "grammar_mistakes": VALID_EVAL_JSON["grammar_mistakes"],
            "spelling_error_count": 1,
        },
        "word_count": 10,
        "sentence_count": 1,
        "paragraph_count": 1,
        "raw_ai_response": {"provider_used": "anthropic_claude"},
    }

    mock_result = WritingEvaluationResult(
        evaluation=EvaluationResponse.model_validate(VALID_EVAL_JSON),
        raw_store={"provider_used": "anthropic_claude"},
        prompt_version="v4",
        model_name="claude-sonnet-4-20250514",
        provider_used="anthropic_claude",
    )

    with (
        patch("app.diagnostic.writing_evaluator._lookup_by_essay_hash", return_value=None),
        patch("app.diagnostic.writing_evaluator._lookup_by_client_attempt", return_value=None),
        patch("app.diagnostic.writing_evaluator.record_evaluate_writing_rate_limit"),
        patch("app.diagnostic.writing_evaluator.writing_eval_configured", return_value=True),
        patch(
            "app.diagnostic.writing_evaluator.evaluate_writing_essay",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
        patch("app.diagnostic.writing_evaluator._persist_evaluation", return_value=persisted),
    ):
        result = asyncio.run(evaluate_diagnostic_writing(body, request))
        assert result.writing_band == 6.5
        assert result.provider == "claude"
        assert len(result.spelling_mistakes) == 1


def criteria_from_row(data: dict) -> dict:
    return {
        "task_achievement": data["task_achievement"],
        "coherence": data["coherence"],
        "lexical_resource": data["lexical_resource"],
        "grammar": data["grammar"],
    }


def test_rate_limit_blocks_fourth_request():
    _buckets.clear()
    request = MagicMock()
    request.headers = {}
    request.client = MagicMock(host="10.0.0.1")

    for _ in range(3):
        check_evaluate_writing_rate_limit(request)

    with pytest.raises(Exception) as exc:
        check_evaluate_writing_rate_limit(request)
    assert getattr(exc.value, "status_code", None) == 429
    _buckets.clear()


def test_evaluate_writing_api_response_schema():
    client = TestClient(app)
    mock_response = DiagnosticEvaluateWritingResponse(
        status="complete",
        evaluation_id="api-eval-id",
        writing_band=6.5,
        scores={
            "task_achievement": 6.0,
            "coherence": 6.5,
            "lexical_resource": 7.0,
            "grammar": 6.0,
        },
        feedback={
            "strengths": ["Good overview"],
            "weaknesses": ["Limited comparison language"],
            "improvement_tips": ["Use more complex structures"],
        },
        metadata={
            "word_count": 200,
            "sentence_count": 10,
            "paragraph_count": 3,
        },
    )

    with patch(
        "app.routers.diagnostic.start_diagnostic_writing_evaluation",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        res = client.post(
            "/api/diagnostic/evaluate-writing",
            json={
                "client_attempt_id": "attempt-api",
                "task_part": 1,
                "question": "The chart shows commuter transport.",
                "essay": "This essay describes the chart in detail with enough words.",
            },
        )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "complete"
    assert body["writing_band"] == 6.5
    assert "evaluation_source" not in body


def test_evaluate_writing_api_returns_202_when_pending():
    from app.diagnostic.evaluation_schemas import DiagnosticEvaluateWritingPendingResponse

    client = TestClient(app)
    mock_response = DiagnosticEvaluateWritingPendingResponse(
        essay_hash="abc123hash",
        client_attempt_id="attempt-pending",
    )

    with patch(
        "app.routers.diagnostic.start_diagnostic_writing_evaluation",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        res = client.post(
            "/api/diagnostic/evaluate-writing",
            json={
                "client_attempt_id": "attempt-pending",
                "task_part": 1,
                "question": "The chart shows commuter transport.",
                "essay": "This essay describes the chart in detail with enough words.",
            },
        )
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "pending"
    assert body["essay_hash"] == "abc123hash"


def test_submit_review_sets_writing_evaluation_fk():
    from app.diagnostic.schemas import DiagnosticReviewSubmitRequest
    from app.diagnostic.submit_review import submit_diagnostic_review

    mock_client = MagicMock()
    lookup_result = MagicMock()
    lookup_result.data = {"id": "eval-123", "overall_band": 6.5}
    mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = lookup_result

    existing = MagicMock()
    existing.data = None
    insert_result = MagicMock()
    insert_result.data = [{"id": "submission-1"}]
    mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = existing
    mock_client.table.return_value.insert.return_value.execute.return_value = insert_result

    body = DiagnosticReviewSubmitRequest(
        client_attempt_id="attempt-1",
        full_name="Test User",
        phone="1234567890",
        email="test@example.com",
        listening_band=7.0,
        reading_band=6.5,
        writing_band=6.5,
        answers={"writing": {"t1": "essay"}},
    )

    with (
        patch("app.diagnostic.submit_review.get_supabase", return_value=mock_client),
        patch(
            "app.diagnostic.submit_review.send_diagnostic_submitted_email",
            new_callable=AsyncMock,
        ),
    ):
        result = asyncio.run(submit_diagnostic_review(body))

    assert result.id == "submission-1"
    insert_call = mock_client.table.return_value.insert.call_args
    payload = insert_call[0][0]
    assert payload["writing_evaluation_id"] == "eval-123"
    assert payload["writing_band"] == 6.5


def test_submit_review_uses_client_band_when_no_ai_evaluation():
    from app.diagnostic.schemas import DiagnosticReviewSubmitRequest
    from app.diagnostic.submit_review import submit_diagnostic_review

    mock_client = MagicMock()
    existing = MagicMock()
    existing.data = None
    insert_result = MagicMock()
    insert_result.data = [{"id": "submission-no-eval"}]
    mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = existing
    mock_client.table.return_value.insert.return_value.execute.return_value = insert_result

    body = DiagnosticReviewSubmitRequest(
        client_attempt_id="attempt-no-eval",
        full_name="Test User",
        phone="1234567890",
        email="test@example.com",
        listening_band=7.0,
        reading_band=6.5,
        writing_band=6.5,
        answers={},
    )

    with (
        patch("app.diagnostic.submit_review._lookup_writing_evaluation", return_value=None),
        patch("app.diagnostic.submit_review.get_supabase", return_value=mock_client),
        patch(
            "app.diagnostic.submit_review.send_diagnostic_submitted_email",
            new_callable=AsyncMock,
        ),
    ):
        result = asyncio.run(submit_diagnostic_review(body))

    assert result.id == "submission-no-eval"
    insert_call = mock_client.table.return_value.insert.call_args
    payload = insert_call[0][0]
    assert payload["writing_band"] == 6.5
    assert "writing_evaluation_id" not in payload


def test_submit_review_ignores_client_writing_band():
    from app.diagnostic.schemas import DiagnosticReviewSubmitRequest
    from app.diagnostic.submit_review import submit_diagnostic_review

    mock_client = MagicMock()
    lookup_result = MagicMock()
    lookup_result.data = {"id": "eval-456", "overall_band": 6.0}
    mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = lookup_result

    existing = MagicMock()
    existing.data = None
    insert_result = MagicMock()
    insert_result.data = [{"id": "submission-2"}]
    mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = existing
    mock_client.table.return_value.insert.return_value.execute.return_value = insert_result

    body = DiagnosticReviewSubmitRequest(
        client_attempt_id="attempt-stale-band",
        full_name="Test User",
        phone="1234567890",
        email=None,
        listening_band=7.0,
        reading_band=6.5,
        writing_band=7.5,
        answers={},
    )

    with patch("app.diagnostic.submit_review.get_supabase", return_value=mock_client):
        asyncio.run(submit_diagnostic_review(body))

    insert_call = mock_client.table.return_value.insert.call_args
    payload = insert_call[0][0]
    assert payload["writing_band"] == 6.0
    assert payload["writing_evaluation_id"] == "eval-456"
