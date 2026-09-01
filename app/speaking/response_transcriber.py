"""Durable, idempotent per-response Whisper transcription worker."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx

from app.speaking import repository as repo
from app.speaking.fluency_metrics import (
    FLUENCY_METRICS_VERSION,
    aggregate_fluency_metrics,
    compute_fluency_metrics,
)
from app.speaking.providers.factory import get_asr_provider
from app.storage.r2 import get_object_bytes

logger = logging.getLogger(__name__)

TRANSCRIPTION_LEASE_SECONDS = 300
TRANSCRIPTION_MAX_ATTEMPTS = 5
TRANSCRIPTION_BACKOFF_SECONDS = (15, 60, 300, 900, 3600)
RECONCILABLE_EVALUATION_STATES = {
    "not_queued",
    "queued",
    "retry_wait",
    "processing",
    "completed",
}
_COMPLETED_EVALUATION_KEYS = {
    "ai_band",
    "evaluation",
    "fluency",
    "grammar",
    "lexical",
    "pronunciation",
}


def _filename_from_key(key: str) -> str:
    name = key.rsplit("/", 1)[-1]
    return name if "." in name else "response.webm"


def retry_delay_seconds(attempt: int) -> int:
    index = min(max(attempt, 1), len(TRANSCRIPTION_BACKOFF_SECONDS)) - 1
    return TRANSCRIPTION_BACKOFF_SECONDS[index]


def is_retryable_transcription_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code in {408, 409, 425, 429} or code >= 500
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "timeout",
            "temporarily",
            "connection",
            "rate limit",
            "r2 get_object",
            "server disconnected",
        )
    )


def _snapshot_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "response_id": str(row["id"]),
        }
        for row in rows
        if str(row.get("transcription_status")) == "completed"
    ]


async def _reconcile_attempt_evaluation(
    attempt_id: UUID,
    *,
    rows: list[dict[str, Any]],
    review: dict[str, Any] | None,
) -> bool:
    confirmed = [row for row in rows if str(row.get("status")) == "confirmed"]
    if not confirmed or any(
        str(row.get("transcription_status")) != "completed" for row in confirmed
    ):
        return False
    if review is None:
        return False
    evaluation_status = str(review.get("evaluation_status") or "not_queued")
    if evaluation_status not in RECONCILABLE_EVALUATION_STATES:
        return False

    from app.speaking.ai_evaluator import run_speaking_evaluation_async

    await run_speaking_evaluation_async(UUID(str(review["id"])))
    return True


async def reconcile_attempt_evaluation_async(attempt_id: UUID) -> bool:
    """Idempotently evaluate an attempt once every confirmed response is transcribed."""
    rows = repo.list_speaking_responses(attempt_id=attempt_id)
    review = repo.get_speaking_review_for_attempt(attempt_id)
    return await _reconcile_attempt_evaluation(
        attempt_id,
        rows=rows,
        review=review,
    )


async def refresh_attempt_fluency_snapshot_async(
    attempt_id: UUID,
) -> dict[str, Any] | None:
    """Refresh review metrics from completed responses in stable manifest order."""
    rows = repo.list_speaking_responses(attempt_id=attempt_id)
    completed = _snapshot_items(rows)
    if not completed:
        return None
    snapshot = aggregate_fluency_metrics(completed)
    review = repo.get_speaking_review_for_attempt(attempt_id)
    if review:
        existing = review.get("ai_scores")
        scores = dict(existing) if isinstance(existing, dict) else {}
        if str(review.get("evaluation_status") or "not_queued") != "completed":
            for key in _COMPLETED_EVALUATION_KEYS:
                scores.pop(key, None)
            if scores.get("status") in {"ai_complete", "ai_stub"}:
                scores["status"] = "pending_multi_response"
        scores["fluency_metrics"] = snapshot["attempt_metrics"]
        scores["part_metrics"] = snapshot["part_metrics"]
        scores["response_metrics"] = snapshot["response_metrics"]
        scores["metrics_version"] = snapshot["version"]
        scores["metrics_source_checksum"] = snapshot["source_checksum"]
        scores["metrics_source_checksums"] = snapshot["source_checksums"]
        scores["transcription_progress"] = repo.transcription_progress(
            attempt_id=attempt_id
        )
        transcript = "\n\n".join(
            str(row.get("transcript") or "").strip()
            for row in completed
            if str(row.get("transcript") or "").strip()
        )
        repo.update_speaking_review_evaluation(
            review_id=UUID(str(review["id"])),
            transcript=transcript or None,
            ai_scores=scores,
        )
        await _reconcile_attempt_evaluation(
            attempt_id,
            rows=rows,
            review=review,
        )
    return snapshot


def refresh_attempt_fluency_snapshot(attempt_id: UUID) -> dict[str, Any] | None:
    """Sync entry point for maintenance jobs and non-async callers."""
    return asyncio.run(refresh_attempt_fluency_snapshot_async(attempt_id))


async def _transcribe_claimed(row: dict[str, Any], lease_token: UUID) -> None:
    response_id = UUID(str(row["id"]))
    attempt_id = UUID(str(row["attempt_id"]))
    attempts = int(row.get("transcription_attempts") or 1)
    try:
        provider = get_asr_provider()
        if not provider.configured():
            raise ValueError(f"ASR provider {provider.name} is not configured")

        audio_key = str(row.get("audio_url") or "")
        if not audio_key:
            raise ValueError("Speaking response has no R2 audio key")
        audio_bytes = get_object_bytes(key=audio_key)
        checksum = hashlib.sha256(audio_bytes).hexdigest()

        cache_matches = (
            str(row.get("content_sha256") or "") == checksum
            and str(row.get("transcription_provider") or "") == provider.name
            and str(row.get("transcription_model") or "") == provider.model
            and str(row.get("metrics_source_checksum") or "") == checksum
            and str(row.get("metrics_version") or "") == FLUENCY_METRICS_VERSION
            and row.get("transcript") is not None
        )
        if cache_matches:
            transcript = str(row.get("transcript") or "")
            words = list(row.get("transcript_words") or [])
            metrics = dict(row.get("fluency_metrics") or {})
        else:
            result = await provider.transcribe(
                audio_bytes=audio_bytes,
                filename=_filename_from_key(audio_key),
            )
            transcript = str(result.get("text") or "").strip()
            words = list(result.get("words") or [])
            metrics = compute_fluency_metrics(
                words=words,
                duration_sec=int(row.get("duration_sec") or 0) or None,
                response_count=1,
                questions_asked=1,
                transcript=transcript,
            )

        completed = repo.complete_speaking_response_transcription(
            response_id=response_id,
            lease_token=lease_token,
            transcript=transcript,
            words=words,
            provider=provider.name,
            model=provider.model,
            content_sha256=checksum,
            fluency_metrics=metrics,
            metrics_version=FLUENCY_METRICS_VERSION,
            completed_at_iso=datetime.now(UTC).isoformat(),
        )
        if completed:
            await refresh_attempt_fluency_snapshot_async(attempt_id)
    except Exception as exc:
        retryable = (
            attempts < TRANSCRIPTION_MAX_ATTEMPTS
            and is_retryable_transcription_error(exc)
        )
        next_attempt = (
            datetime.now(UTC) + timedelta(seconds=retry_delay_seconds(attempts))
            if retryable
            else None
        )
        repo.fail_speaking_response_transcription(
            response_id=response_id,
            lease_token=lease_token,
            retryable=retryable,
            error=f"{type(exc).__name__}: {exc}",
            next_attempt_at_iso=next_attempt.isoformat() if next_attempt else None,
        )
        logger.exception("Response transcription failed for %s", response_id)


async def transcribe_response_async(response_id: UUID) -> bool:
    lease_token = uuid4()
    row = repo.claim_speaking_response_transcription(
        response_id=response_id,
        lease_token=lease_token,
        lease_seconds=TRANSCRIPTION_LEASE_SECONDS,
    )
    if row is None:
        return False
    await _transcribe_claimed(row, lease_token)
    return True


def transcribe_response(response_id: UUID) -> None:
    """Sync entry point for FastAPI BackgroundTasks."""
    asyncio.run(transcribe_response_async(response_id))


async def reconcile_attempt_transcriptions_async(
    attempt_id: UUID,
    *,
    verify_completed_checksums: bool = False,
) -> int:
    """Claim due/expired jobs; safe to run repeatedly from a scheduler."""
    processed = 0
    provider = get_asr_provider()
    for row in repo.list_speaking_responses(attempt_id=attempt_id):
        state = str(row.get("transcription_status") or "not_queued")
        if str(row.get("status")) != "confirmed":
            continue
        if state == "completed":
            if not verify_completed_checksums:
                continue
            try:
                actual_checksum = hashlib.sha256(
                    get_object_bytes(key=str(row["audio_url"]))
                ).hexdigest()
            except Exception:
                logger.exception(
                    "Could not reconcile response object %s", row.get("id")
                )
                continue
            identity_matches = (
                str(row.get("content_sha256") or "") == actual_checksum
                and str(row.get("transcription_provider") or "") == provider.name
                and str(row.get("transcription_model") or "") == provider.model
                and str(row.get("metrics_source_checksum") or "")
                == actual_checksum
                and str(row.get("metrics_version") or "")
                == FLUENCY_METRICS_VERSION
            )
            if identity_matches:
                continue
            repo.reset_speaking_response_transcription(
                response_id=UUID(str(row["id"])),
                reason="Audio checksum, ASR provider/model, or metrics version changed.",
            )
        if state == "not_queued":
            repo.queue_speaking_response_transcription(
                response_id=UUID(str(row["id"])),
                attempt_id=attempt_id,
            )
        claimed = await transcribe_response_async(UUID(str(row["id"])))
        processed += int(claimed)
    try:
        await reconcile_attempt_evaluation_async(attempt_id)
    except Exception:
        logger.exception("Could not reconcile attempt evaluation for %s", attempt_id)
    return processed


def reconcile_attempt_transcriptions(
    attempt_id: UUID,
    *,
    verify_completed_checksums: bool = False,
) -> int:
    """Sync entry point for FastAPI BackgroundTasks and schedulers."""
    return asyncio.run(
        reconcile_attempt_transcriptions_async(
            attempt_id,
            verify_completed_checksums=verify_completed_checksums,
        )
    )
