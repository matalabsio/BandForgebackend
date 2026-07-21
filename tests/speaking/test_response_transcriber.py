"""Durability tests for per-response Whisper jobs."""

from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import pytest

from app.speaking import response_transcriber as worker
from app.speaking import repository

ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
RESPONSE_ID = UUID("11111111-1111-4111-8111-111111111111")


def _row(**changes) -> dict:
    values = {
        "id": str(RESPONSE_ID),
        "attempt_id": str(ATTEMPT_ID),
        "status": "confirmed",
        "transcription_status": "processing",
        "transcription_attempts": 1,
        "audio_url": "speaking/a/responses/01.webm",
        "duration_sec": 10,
        "part": 1,
        "sequence_number": 1,
    }
    values.update(changes)
    return values


def _provider(*, configured: bool = True) -> Mock:
    provider = Mock()
    provider.name = "groq_whisper"
    provider.model = "whisper-large-v3-turbo"
    provider.configured.return_value = configured
    provider.transcribe = AsyncMock(
        return_value={
            "text": "hello world",
            "words": [
                {"word": "hello", "start": 0.0, "end": 0.3},
                {"word": "world", "start": 0.4, "end": 0.8},
            ],
        }
    )
    return provider


def test_atomic_claim_allows_only_one_concurrent_worker():
    provider = _provider()

    async def run_both() -> list[bool]:
        return await asyncio.gather(
            worker.transcribe_response_async(RESPONSE_ID),
            worker.transcribe_response_async(RESPONSE_ID),
        )

    with (
        patch.object(
            worker.repo,
            "claim_speaking_response_transcription",
            side_effect=[_row(), None],
        ),
        patch.object(worker, "get_asr_provider", return_value=provider),
        patch.object(worker, "get_object_bytes", return_value=b"audio"),
        patch.object(
            worker.repo,
            "complete_speaking_response_transcription",
            return_value=False,
        ),
    ):
        claimed = asyncio.run(run_both())
    assert claimed == [True, False]
    provider.transcribe.assert_awaited_once()


def test_retryable_failure_persists_backoff_without_sleeping():
    with (
        patch.object(
            worker.repo,
            "claim_speaking_response_transcription",
            return_value=_row(transcription_attempts=2),
        ),
        patch.object(worker, "get_asr_provider", return_value=_provider()),
        patch.object(
            worker,
            "get_object_bytes",
            side_effect=RuntimeError("R2 get_object temporarily unavailable"),
        ),
        patch.object(
            worker.repo,
            "fail_speaking_response_transcription",
            return_value=True,
        ) as failed,
    ):
        assert asyncio.run(worker.transcribe_response_async(RESPONSE_ID)) is True
    assert failed.call_args.kwargs["retryable"] is True
    assert failed.call_args.kwargs["next_attempt_at_iso"] is not None


def test_permanent_provider_configuration_failure_does_not_retry():
    with (
        patch.object(
            worker.repo,
            "claim_speaking_response_transcription",
            return_value=_row(),
        ),
        patch.object(
            worker, "get_asr_provider", return_value=_provider(configured=False)
        ),
        patch.object(
            worker.repo,
            "fail_speaking_response_transcription",
            return_value=True,
        ) as failed,
    ):
        asyncio.run(worker.transcribe_response_async(RESPONSE_ID))
    assert failed.call_args.kwargs["retryable"] is False
    assert failed.call_args.kwargs["next_attempt_at_iso"] is None


def test_partial_failure_snapshot_uses_only_completed_responses():
    completed = _row(
        transcription_status="completed",
        fluency_metrics={
            "word_count": 10,
            "total_speaking_seconds": 5,
            "long_pauses": 0,
        },
        content_sha256="a" * 64,
        metrics_source_checksum="a" * 64,
        transcription_provider="groq_whisper",
        transcription_model="whisper-large-v3-turbo",
        transcript="complete",
    )
    failed = _row(
        id="22222222-2222-4222-8222-222222222222",
        sequence_number=2,
        transcription_status="failed",
    )
    with (
        patch.object(
            worker.repo, "list_speaking_responses", return_value=[failed, completed]
        ),
        patch.object(worker.repo, "get_speaking_review_for_attempt", return_value=None),
    ):
        snapshot = worker.refresh_attempt_fluency_snapshot(ATTEMPT_ID)
    assert snapshot is not None
    assert snapshot["attempt_metrics"]["response_count"] == 1


def test_last_transcript_awaits_evaluation_inside_active_event_loop():
    completed_row = _row(
        transcription_status="completed",
        transcript="hello world",
        fluency_metrics={
            "word_count": 2,
            "total_speaking_seconds": 1,
            "long_pauses": 0,
        },
        content_sha256=hashlib.sha256(b"audio").hexdigest(),
        metrics_source_checksum=hashlib.sha256(b"audio").hexdigest(),
    )
    review_id = UUID("99999999-9999-4999-8999-999999999999")
    review = {
        "id": str(review_id),
        "evaluation_status": "not_queued",
        "ai_scores": {
            "status": "ai_complete",
            "ai_band": 7.0,
            "evaluation": {"band_scores": {"overall": 7.0}},
        },
    }
    evaluate = AsyncMock()
    with (
        patch.object(
            worker.repo,
            "claim_speaking_response_transcription",
            return_value=_row(),
        ),
        patch.object(worker, "get_asr_provider", return_value=_provider()),
        patch.object(worker, "get_object_bytes", return_value=b"audio"),
        patch.object(
            worker.repo,
            "complete_speaking_response_transcription",
            return_value=True,
        ),
        patch.object(
            worker.repo,
            "list_speaking_responses",
            return_value=[completed_row],
        ),
        patch.object(
            worker.repo,
            "get_speaking_review_for_attempt",
            return_value=review,
        ),
        patch.object(
            worker.repo,
            "transcription_progress",
            return_value={
                "total": 1,
                "queued": 0,
                "processing": 0,
                "completed": 1,
                "failed": 0,
            },
        ),
        patch.object(
            worker.repo,
            "update_speaking_review_evaluation",
        ) as update_review,
        patch(
            "app.speaking.ai_evaluator.run_speaking_evaluation_async",
            new=evaluate,
        ),
    ):
        assert asyncio.run(worker.transcribe_response_async(RESPONSE_ID)) is True

    evaluate.assert_awaited_once_with(review_id)
    pending_scores = update_review.call_args.kwargs["ai_scores"]
    assert pending_scores["status"] == "pending_multi_response"
    assert "evaluation" not in pending_scores
    assert "ai_band" not in pending_scores


@pytest.mark.parametrize("evaluation_status", ["not_queued", "queued", "retry_wait"])
def test_reconcile_all_transcribed_review_evaluation_states(evaluation_status):
    completed_row = _row(transcription_status="completed")
    review_id = UUID("99999999-9999-4999-8999-999999999999")
    evaluate = AsyncMock()
    with (
        patch.object(
            worker.repo,
            "list_speaking_responses",
            return_value=[completed_row],
        ),
        patch.object(
            worker.repo,
            "get_speaking_review_for_attempt",
            return_value={
                "id": str(review_id),
                "evaluation_status": evaluation_status,
            },
        ),
        patch(
            "app.speaking.ai_evaluator.run_speaking_evaluation_async",
            new=evaluate,
        ),
    ):
        reconciled = asyncio.run(
            worker.reconcile_attempt_evaluation_async(ATTEMPT_ID)
        )

    assert reconciled is True
    evaluate.assert_awaited_once_with(review_id)


def test_reconciliation_invalidates_changed_audio_checksum():
    old = _row(
        transcription_status="completed",
        content_sha256="a" * 64,
        metrics_source_checksum="a" * 64,
        metrics_version=worker.FLUENCY_METRICS_VERSION,
        transcription_provider="groq_whisper",
        transcription_model="whisper-large-v3-turbo",
    )
    new_audio = b"replacement audio"
    assert hashlib.sha256(new_audio).hexdigest() != old["content_sha256"]
    with (
        patch.object(worker.repo, "list_speaking_responses", return_value=[old]),
        patch.object(worker, "get_asr_provider", return_value=_provider()),
        patch.object(worker, "get_object_bytes", return_value=new_audio),
        patch.object(
            worker.repo,
            "reset_speaking_response_transcription",
            return_value=True,
        ) as reset,
        patch.object(worker, "transcribe_response_async", new=AsyncMock(return_value=False)),
        patch.object(worker.repo, "get_speaking_review_for_attempt", return_value=None),
    ):
        worker.reconcile_attempt_transcriptions(
            ATTEMPT_ID, verify_completed_checksums=True
        )
    reset.assert_called_once()


def test_progress_counts_retry_wait_as_queued():
    with patch.object(
        repository,
        "list_speaking_responses",
        return_value=[
            {"transcription_status": "completed"},
            {"transcription_status": "processing"},
            {"transcription_status": "retry_wait"},
            {"transcription_status": "failed"},
        ],
    ):
        counts = repository.transcription_progress(attempt_id=ATTEMPT_ID)
    assert counts == {
        "total": 4,
        "queued": 1,
        "processing": 1,
        "completed": 1,
        "failed": 1,
    }
