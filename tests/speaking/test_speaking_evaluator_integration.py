"""Integration tests with mocked ASR + evaluation providers."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

REVIEW_ID = UUID("11111111-1111-4111-8111-111111111111")
ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
MOCK_TEST_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def _eval_json(transcript: str) -> str:
    snippet = transcript[:40]
    payload = {
        "band_scores": {
            "FC": 6.0,
            "LR": 6.0,
            "GRA": 5.5,
            "P": 6.0,
            "P_confidence": 0.7,
            "overall": 6.0,
        },
        "part_performance": [
            {"part": 1, "note": "Good flow.", "band_estimate": 6.0}
        ],
        "evidence_quotes": [
            {"quote": snippet, "criterion": "FC", "polarity": "strength", "part": 1},
            {"quote": snippet, "criterion": "LR", "polarity": "strength", "part": 1},
            {"quote": snippet, "criterion": "GRA", "polarity": "weakness", "part": 1},
            {"quote": snippet, "criterion": "P", "polarity": "strength", "part": 1},
        ],
        "recurring_patterns": [
            {
                "pattern": "simple structures",
                "criterion": "GRA",
                "frequency": "often",
                "examples": ["because"],
            }
        ],
        "strengths": ["Clear ideas"],
        "improvements": ["Add examples"],
        "vocabulary_highlights": ["hometown"],
        "reviewer_flags": [],
        "next_band_advice": "Extend answers.",
    }
    return json.dumps(payload)


def _mock_asr_provider(transcript: str, words: list) -> MagicMock:
    provider = MagicMock()
    provider.name = "openai_whisper"
    provider.model = "whisper-1"
    provider.configured.return_value = True
    provider.transcribe = AsyncMock(
        return_value={"text": transcript, "words": words},
    )
    return provider


def _mock_eval_provider(transcript: str) -> MagicMock:
    from app.speaking.evaluation_schemas import SpeakingEvaluation, parse_json_content

    evaluation = SpeakingEvaluation.model_validate(parse_json_content(_eval_json(transcript)))
    provider = MagicMock()
    provider.name = "anthropic_claude"
    provider.model = "claude-test"
    provider.configured.return_value = True
    provider.evaluate = AsyncMock(return_value=evaluation)
    return provider


def test_evaluate_review_live_mocked_providers():
    from app.speaking.speaking_evaluator import process_speaking_review_async

    transcript = "I come from a small city and I enjoy living there."
    words = [
        {"word": "I", "start": 0.0, "end": 0.1},
        {"word": "come", "start": 0.12, "end": 0.4},
    ]

    review_row = {
        "id": str(REVIEW_ID),
        "attempt_id": str(ATTEMPT_ID),
        "audio_url": "speaking/x/part-1/recording.webm",
        "submission_meta": {"part": 1, "duration_sec": 30},
        "ai_scores": {"status": "pending"},
        "transcript": None,
    }

    mock_asr = _mock_asr_provider(transcript, words)
    mock_eval = _mock_eval_provider(transcript)

    with (
        patch("app.speaking.speaking_evaluator.get_settings") as mock_settings,
        patch(
            "app.speaking.speaking_evaluator.repo.get_speaking_review_by_id",
            return_value=review_row,
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.get_attempt",
            return_value={"id": str(ATTEMPT_ID), "mock_test_id": str(MOCK_TEST_ID)},
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.list_questions_for_part",
            return_value=[{"prompt": "Where are you from?"}],
        ),
        patch(
            "app.speaking.speaking_evaluator.get_object_bytes",
            return_value=b"fake-audio",
        ),
        patch(
            "app.speaking.speaking_evaluator.get_asr_provider",
            return_value=mock_asr,
        ),
        patch(
            "app.speaking.speaking_evaluator.get_eval_provider_chain",
            return_value=[mock_eval],
        ),
        patch(
            "app.speaking.speaking_evaluator.repo.update_speaking_review_evaluation"
        ) as update_eval,
    ):
        settings = mock_settings.return_value
        settings.speaking_eval_stub = False
        settings.asr_provider = "openai"
        settings.llm_provider = "claude"

        asyncio.run(process_speaking_review_async(REVIEW_ID))

        update_eval.assert_called_once()
        ai_scores = update_eval.call_args.kwargs["ai_scores"]
        assert ai_scores["status"] == "ai_complete"
        assert ai_scores["fluency"] == 6.0
        assert ai_scores["provider_version"] == 1
        assert ai_scores["provider_asr"] == "openai_whisper"
        assert ai_scores["provider_eval"] == "anthropic_claude"
        assert update_eval.call_args.kwargs["transcript"] == transcript
