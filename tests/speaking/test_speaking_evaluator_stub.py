"""Stub-mode speaking evaluator tests."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import httpx
import pytest

REVIEW_ID = UUID("11111111-1111-4111-8111-111111111111")
ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
MOCK_TEST_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


@pytest.fixture
def mock_review_row():
    return {
        "id": str(REVIEW_ID),
        "attempt_id": str(ATTEMPT_ID),
        "audio_url": "speaking/test/part-1/recording.webm",
        "submission_meta": {"part": 1, "duration_sec": 45},
        "ai_scores": {"status": "pending"},
        "transcript": None,
    }


def test_process_speaking_review_stub_persists(mock_review_row):
    from app.speaking.speaking_evaluator import process_speaking_review

    with (
        patch("app.speaking.speaking_evaluator.get_settings") as mock_settings,
        patch(
            "app.speaking.speaking_evaluator.repo.get_speaking_review_by_id",
            return_value=mock_review_row,
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.get_attempt",
            return_value={
                "id": str(ATTEMPT_ID),
                "mock_test_id": str(MOCK_TEST_ID),
            },
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.list_questions_for_part",
            return_value=[{"prompt": "Tell me about your hometown."}],
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.update_speaking_review_evaluation"
        ) as update_eval,
    ):
        settings = mock_settings.return_value
        settings.speaking_eval_stub = True
        settings.openai_whisper_model = "whisper-1"
        settings.anthropic_model = "claude-test"

        process_speaking_review(REVIEW_ID)

        update_eval.assert_called_once()
        kwargs = update_eval.call_args.kwargs
        assert kwargs["review_id"] == REVIEW_ID
        assert kwargs["transcript"]
        assert kwargs["ai_scores"]["status"] == "ai_stub"
        assert kwargs["ai_scores"]["fluency"] is not None
        assert kwargs["ai_scores"]["evaluation"]["band_scores"]["overall"] is not None


def test_async_evaluator_entry_point_runs_inside_active_event_loop():
    from app.speaking.ai_evaluator import run_speaking_evaluation_async

    process = AsyncMock()
    with patch(
        "app.speaking.ai_evaluator.process_speaking_review_async",
        new=process,
    ):
        asyncio.run(run_speaking_evaluation_async(REVIEW_ID))

    process.assert_awaited_once_with(REVIEW_ID)


def test_full_attempt_stub_uses_durable_claim_and_scoped_evidence():
    from app.speaking.speaking_evaluator import process_speaking_review

    response_id = "33333333-3333-4333-8333-333333333333"
    question_id = "44444444-4444-4444-8444-444444444444"
    review = {
        "id": str(REVIEW_ID),
        "attempt_id": str(ATTEMPT_ID),
        "submission_meta": {
            "manifest_hash": "a" * 64,
            "responses": [{"response_id": response_id}],
        },
        "ai_scores": {"status": "pending_multi_response"},
    }
    attempt = {
        "id": str(ATTEMPT_ID),
        "mock_test_id": str(MOCK_TEST_ID),
        "speaking_manifest": [{
            "id": question_id,
            "prompt": "Where are you from?",
        }],
    }
    response = {
        "id": response_id,
        "question_id": question_id,
        "part": 1,
        "sequence_number": 1,
        "transcription_status": "completed",
        "transcript": "I answer one",
        "content_sha256": "b" * 64,
        "fluency_metrics": {
            "word_count": 3,
            "total_speaking_seconds": 2,
            "long_pauses": 0,
        },
    }
    with (
        patch("app.speaking.speaking_evaluator.get_settings") as settings,
        patch(
            "app.speaking.speaking_evaluator.repo.get_speaking_review_by_id",
            return_value=review,
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.get_attempt",
            return_value=attempt,
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.list_speaking_responses",
            return_value=[response],
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.claim_speaking_attempt_evaluation",
            return_value={"evaluation_attempts": 1},
        ) as claim,
        patch(
            "app.speaking.speaking_evaluator.repo.complete_speaking_attempt_evaluation"
        ) as complete,
    ):
        settings.return_value.speaking_eval_stub = True
        process_speaking_review(REVIEW_ID)

    claim.assert_called_once()
    payload = complete.call_args.kwargs["ai_scores"]
    evidence = payload["evaluation"]["evidence_quotes"][0]
    assert payload["prompt_version"] == "v4-human-report-alignment"
    assert evidence["response_id"] == response_id
    assert evidence["question_id"] == question_id
    assert "low_confidence_pronunciation" in payload["evaluation"]["reviewer_flags"]
    pronunciation = next(
        item
        for item in payload["evaluation"]["evidence_quotes"]
        if item["criterion"] == "P"
    )
    assert pronunciation["suggestion"].startswith(
        "Transcript-inferred advisory only:"
    )
    assert payload["evaluation"]["band_scores"]["P_inference_source"] == (
        "transcript_inferred"
    )
    assert payload["evaluation"]["band_scores"]["P_advisory_only"] is True


def test_failed_attempt_does_not_retain_completed_evaluation_payload():
    from app.speaking.speaking_evaluator import process_speaking_review_async

    response_id = "33333333-3333-4333-8333-333333333333"
    question_id = "44444444-4444-4444-8444-444444444444"
    review = {
        "id": str(REVIEW_ID),
        "attempt_id": str(ATTEMPT_ID),
        "submission_meta": {
            "manifest_hash": "a" * 64,
            "responses": [{"response_id": response_id}],
        },
        "ai_scores": {
            "status": "ai_complete",
            "ai_band": 7.0,
            "fluency": 7.0,
            "lexical": 7.0,
            "grammar": 7.0,
            "pronunciation": 7.0,
            "evaluation": {"band_scores": {"overall": 7.0}},
        },
    }
    attempt = {
        "id": str(ATTEMPT_ID),
        "mock_test_id": str(MOCK_TEST_ID),
        "speaking_manifest": [{"id": question_id, "prompt": "Where are you from?"}],
    }
    response = {
        "id": response_id,
        "question_id": question_id,
        "part": 1,
        "sequence_number": 1,
        "transcription_status": "completed",
        "transcript": "I answer one",
        "content_sha256": "b" * 64,
        "fluency_metrics": {
            "word_count": 3,
            "total_speaking_seconds": 2,
            "long_pauses": 0,
        },
    }
    provider = Mock()
    provider.name = "anthropic"
    provider.model = "claude-test"
    provider.configured.return_value = True
    provider.evaluate_attempt = AsyncMock(
        side_effect=httpx.ReadTimeout("evaluation timed out")
    )

    with (
        patch("app.speaking.speaking_evaluator.get_settings") as settings,
        patch(
            "app.speaking.speaking_evaluator.repo.get_speaking_review_by_id",
            return_value=review,
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.get_attempt",
            return_value=attempt,
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.list_speaking_responses",
            return_value=[response],
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.claim_speaking_attempt_evaluation",
            return_value={"evaluation_attempts": 1},
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.fail_speaking_attempt_evaluation",
            return_value=True,
        ) as fail,
        patch(
            "app.speaking.speaking_evaluator.get_eval_provider_chain",
            return_value=[provider],
        ),
    ):
        settings.return_value.speaking_eval_stub = False
        asyncio.run(process_speaking_review_async(REVIEW_ID))

    payload = fail.call_args.kwargs["ai_scores"]
    assert payload["status"] == "ai_failed"
    assert "evaluation" not in payload
    assert "ai_band" not in payload
    assert "fluency" not in payload
    assert fail.call_args.kwargs["retryable"] is True
