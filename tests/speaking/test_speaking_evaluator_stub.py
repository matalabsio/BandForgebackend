"""Stub-mode speaking evaluator tests."""

from unittest.mock import patch
from uuid import UUID

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
