"""Supabase accessors for the Speaking module."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.db.supabase_client import execute_with_retry, get_supabase

QUESTION_PUBLIC_COLUMNS = (
    "id, mock_test_id, module, question_type, question_number, part, prompt, options"
)


def _exec(query):
    return execute_with_retry(query.execute, retries=3, base_delay_s=0.2)


def get_mock_test(mock_test_id: UUID, *, allow_unpublished: bool = False) -> dict[str, Any]:
    client = get_supabase()
    result = _exec(
        client.table("mock_tests")
        .select("id, title, description, is_published")
        .eq("id", str(mock_test_id))
        .limit(1)
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")
    row = rows[0]
    if not row.get("is_published") and not allow_unpublished:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")
    return row


def list_questions_for_part(*, mock_test_id: UUID, part: int) -> list[dict[str, Any]]:
    client = get_supabase()
    result = _exec(
        client.table("questions")
        .select(QUESTION_PUBLIC_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "speaking")
        .eq("part", part)
        .order("question_number")
    )
    return list(result.data or [])


def list_speaking_questions(*, mock_test_id: UUID) -> list[dict[str, Any]]:
    client = get_supabase()
    result = _exec(
        client.table("questions")
        .select(QUESTION_PUBLIC_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "speaking")
        .order("part")
        .order("question_number")
    )
    return list(result.data or [])


def find_in_progress_speaking_attempt(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    part: int,
    mock_attempt_id: UUID | None = None,
) -> dict[str, Any] | None:
    client = get_supabase()
    query = (
        client.table("test_attempts")
        .select("id, started_at, status, part, mock_attempt_id")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "speaking")
        .eq("status", "in_progress")
        .eq("part", part)
    )
    if mock_attempt_id is not None:
        query = query.eq("mock_attempt_id", str(mock_attempt_id))
    else:
        query = query.is_("mock_attempt_id", "null")
    result = _exec(query.limit(1))
    rows = result.data or []
    return rows[0] if rows else None


def insert_speaking_attempt(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID | None = None,
    part: int,
    speaking_manifest: list[dict[str, Any]] | None = None,
    speaking_manifest_hash: str | None = None,
) -> dict[str, Any]:
    client = get_supabase()
    payload: dict[str, Any] = {
        "user_id": str(user_id),
        "mock_test_id": str(mock_test_id),
        "module": "speaking",
        "status": "in_progress",
        "part": part,
    }
    if mock_attempt_id is not None:
        payload["mock_attempt_id"] = str(mock_attempt_id)
    if speaking_manifest is not None:
        payload["speaking_manifest"] = speaking_manifest
    if speaking_manifest_hash is not None:
        payload["speaking_manifest_hash"] = speaking_manifest_hash
    insert = _exec(client.table("test_attempts").insert(payload))
    if not insert.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to create speaking attempt.",
        )
    return insert.data[0]


def get_attempt(attempt_id: UUID) -> dict[str, Any]:
    client = get_supabase()
    result = _exec(
        client.table("test_attempts")
        .select(
            "id, user_id, mock_test_id, module, status, started_at, completed_at, "
            "part, mock_attempt_id, speaking_manifest, speaking_manifest_hash, "
            "mock_tests(title, catalog_number)"
        )
        .eq("id", str(attempt_id))
        .limit(1)
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test attempt not found.")
    return rows[0]


def update_attempt_manifest(
    *,
    attempt_id: UUID,
    manifest: list[dict[str, Any]],
    manifest_hash: str,
) -> None:
    client = get_supabase()
    _exec(
        client.table("test_attempts")
        .update(
            {
                "speaking_manifest": manifest,
                "speaking_manifest_hash": manifest_hash,
            }
        )
        .eq("id", str(attempt_id))
        .eq("status", "in_progress")
    )


def abandon_speaking_attempt(*, attempt_id: UUID) -> None:
    client = get_supabase()
    _exec(
        client.table("test_attempts").update({"status": "abandoned"}).eq(
            "id", str(attempt_id)
        )
    )


def mark_attempt_completed(attempt_id: UUID, *, completed_at_iso: str) -> dict[str, Any]:
    client = get_supabase()
    updated = _exec(
        client.table("test_attempts")
        .update({"status": "completed", "completed_at": completed_at_iso})
        .eq("id", str(attempt_id))
    )
    if not updated.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to complete speaking attempt.",
        )
    return updated.data[0]


def get_speaking_review_for_attempt(attempt_id: UUID) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.table("speaking_reviews")
        .select("*")
        .eq("attempt_id", str(attempt_id))
        .order("created_at", desc=True)
        .limit(1)
    )
    rows = result.data or []
    return rows[0] if rows else None


def get_speaking_review_by_id(review_id: UUID) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.table("speaking_reviews")
        .select("*")
        .eq("id", str(review_id))
        .limit(1)
    )
    rows = result.data or []
    return rows[0] if rows else None


def update_speaking_review_ai_scores(
    *, review_id: UUID, ai_scores: dict[str, Any]
) -> None:
    client = get_supabase()
    _exec(
        client.table("speaking_reviews")
        .update({"ai_scores": ai_scores})
        .eq("id", str(review_id))
    )


def update_speaking_review_evaluation(
    *,
    review_id: UUID,
    transcript: str | None,
    ai_scores: dict[str, Any],
) -> None:
    client = get_supabase()
    payload: dict[str, Any] = {"ai_scores": ai_scores}
    if transcript is not None:
        payload["transcript"] = transcript
    _exec(
        client.table("speaking_reviews")
        .update(payload)
        .eq("id", str(review_id))
    )


def claim_speaking_attempt_evaluation(
    *, review_id: UUID, fingerprint: str, lease_token: UUID, lease_seconds: int
) -> dict[str, Any] | None:
    result = _exec(
        get_supabase().rpc(
            "claim_speaking_attempt_evaluation",
            {
                "p_review_id": str(review_id),
                "p_fingerprint": fingerprint,
                "p_lease_token": str(lease_token),
                "p_lease_seconds": lease_seconds,
            },
        )
    )
    rows = result.data or []
    return rows[0] if rows else None


def complete_speaking_attempt_evaluation(
    *,
    review_id: UUID,
    lease_token: UUID,
    fingerprint: str,
    transcript: str,
    ai_scores: dict[str, Any],
    completed_at_iso: str,
) -> bool:
    result = _exec(
        get_supabase()
        .table("speaking_reviews")
        .update(
            {
                "evaluation_status": "completed",
                "evaluation_input_fingerprint": fingerprint,
                "evaluation_completed_at": completed_at_iso,
                "evaluation_error": None,
                "evaluation_lease_token": None,
                "evaluation_lease_expires_at": None,
                "evaluation_next_attempt_at": None,
                "transcript": transcript,
                "ai_scores": ai_scores,
            }
        )
        .eq("id", str(review_id))
        .eq("evaluation_status", "processing")
        .eq("evaluation_lease_token", str(lease_token))
    )
    return bool(result.data)


def fail_speaking_attempt_evaluation(
    *,
    review_id: UUID,
    lease_token: UUID,
    retryable: bool,
    error: str,
    next_attempt_at_iso: str | None,
    ai_scores: dict[str, Any],
) -> bool:
    result = _exec(
        get_supabase()
        .table("speaking_reviews")
        .update(
            {
                "evaluation_status": "retry_wait" if retryable else "failed",
                "evaluation_error": error[:2000],
                "evaluation_next_attempt_at": next_attempt_at_iso,
                "evaluation_lease_token": None,
                "evaluation_lease_expires_at": None,
                "ai_scores": ai_scores,
            }
        )
        .eq("id", str(review_id))
        .eq("evaluation_status", "processing")
        .eq("evaluation_lease_token", str(lease_token))
    )
    return bool(result.data)


def insert_speaking_review(
    *,
    attempt_id: UUID,
    audio_key: str,
    submission_meta: dict[str, Any],
    student_name: str | None,
    ai_scores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client = get_supabase()
    meta = {**submission_meta}
    if student_name:
        meta["student_display_name"] = student_name
    row: dict[str, Any] = {
        "attempt_id": str(attempt_id),
        "status": "pending",
        "audio_url": audio_key,
        "submission_meta": meta,
    }
    if ai_scores is not None:
        row["ai_scores"] = ai_scores
    insert = _exec(client.table("speaking_reviews").insert(row))
    if not insert.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to queue speaking review.",
        )
    return insert.data[0]


def get_speaking_response(
    *, attempt_id: UUID, question_id: UUID
) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses")
        .select("*")
        .eq("attempt_id", str(attempt_id))
        .eq("question_id", str(question_id))
        .limit(1)
    )
    rows = result.data or []
    return rows[0] if rows else None


def get_speaking_response_by_id(
    *, attempt_id: UUID, response_id: UUID
) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses")
        .select("*")
        .eq("attempt_id", str(attempt_id))
        .eq("id", str(response_id))
        .limit(1)
    )
    rows = result.data or []
    return rows[0] if rows else None


def list_speaking_responses(*, attempt_id: UUID) -> list[dict[str, Any]]:
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses")
        .select("*")
        .eq("attempt_id", str(attempt_id))
        .order("sequence_number")
    )
    return list(result.data or [])


def insert_speaking_response(
    *,
    attempt_id: UUID,
    question_id: UUID,
    part: int,
    sequence_number: int,
    audio_key: str,
    content_type: str,
    duration_sec: int,
    size_bytes: int,
    content_sha256: str,
) -> dict[str, Any]:
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses").insert(
            {
                "attempt_id": str(attempt_id),
                "question_id": str(question_id),
                "part": part,
                "sequence_number": sequence_number,
                "audio_url": audio_key,
                "content_type": content_type,
                "duration_sec": duration_sec,
                "size_bytes": size_bytes,
                "content_sha256": content_sha256,
                "status": "confirmed",
            }
        )
    )
    if not result.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to persist speaking response.",
        )
    return result.data[0]


def insert_speaking_response_session(
    *,
    attempt_id: UUID,
    question_id: UUID,
    part: int,
    sequence_number: int,
    audio_key: str,
    content_type: str,
    duration_sec: int,
    size_bytes: int,
    idempotency_key: str,
    expires_at_iso: str,
) -> dict[str, Any]:
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses").insert(
            {
                "attempt_id": str(attempt_id),
                "question_id": str(question_id),
                "part": part,
                "sequence_number": sequence_number,
                "audio_url": audio_key,
                "content_type": content_type,
                "duration_sec": duration_sec,
                "size_bytes": size_bytes,
                "content_sha256": None,
                "status": "pending_upload",
                "idempotency_key": idempotency_key,
                "upload_expires_at": expires_at_iso,
            }
        )
    )
    if not result.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to create speaking upload session.",
        )
    return result.data[0]


def confirm_speaking_response(
    *,
    response_id: UUID,
    attempt_id: UUID,
    confirmed_at_iso: str,
) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses")
        .update(
            {
                "status": "confirmed",
                "confirmed_at": confirmed_at_iso,
                "updated_at": confirmed_at_iso,
            }
        )
        .eq("id", str(response_id))
        .eq("attempt_id", str(attempt_id))
        .eq("status", "pending_upload")
    )
    rows = result.data or []
    return rows[0] if rows else None


def renew_speaking_response_session(
    *,
    response_id: UUID,
    attempt_id: UUID,
    expires_at_iso: str,
) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses")
        .update({"upload_expires_at": expires_at_iso})
        .eq("id", str(response_id))
        .eq("attempt_id", str(attempt_id))
        .eq("status", "pending_upload")
    )
    rows = result.data or []
    return rows[0] if rows else None


def queue_speaking_response_transcription(
    *,
    response_id: UUID,
    attempt_id: UUID,
) -> dict[str, Any] | None:
    """Persist queue state before any in-process worker is scheduled."""
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses")
        .update(
            {
                "transcription_status": "queued",
                "transcription_next_attempt_at": None,
                "transcription_error": None,
            }
        )
        .eq("id", str(response_id))
        .eq("attempt_id", str(attempt_id))
        .eq("status", "confirmed")
        .eq("transcription_status", "not_queued")
    )
    rows = result.data or []
    return rows[0] if rows else None


def claim_speaking_response_transcription(
    *,
    response_id: UUID,
    lease_token: UUID,
    lease_seconds: int,
) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.rpc(
            "claim_speaking_response_transcription",
            {
                "p_response_id": str(response_id),
                "p_lease_token": str(lease_token),
                "p_lease_seconds": lease_seconds,
            },
        )
    )
    rows = result.data or []
    return rows[0] if rows else None


def complete_speaking_response_transcription(
    *,
    response_id: UUID,
    lease_token: UUID,
    transcript: str,
    words: list[dict[str, Any]],
    provider: str,
    model: str,
    content_sha256: str,
    fluency_metrics: dict[str, Any],
    metrics_version: str,
    completed_at_iso: str,
) -> bool:
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses")
        .update(
            {
                "transcription_status": "completed",
                "transcript": transcript,
                "transcript_words": words,
                "transcription_provider": provider,
                "transcription_model": model,
                "content_sha256": content_sha256,
                "fluency_metrics": fluency_metrics,
                "metrics_version": metrics_version,
                "metrics_source_checksum": content_sha256,
                "transcribed_at": completed_at_iso,
                "transcription_lease_token": None,
                "transcription_lease_expires_at": None,
                "transcription_next_attempt_at": None,
                "transcription_error": None,
                "updated_at": completed_at_iso,
            }
        )
        .eq("id", str(response_id))
        .eq("transcription_status", "processing")
        .eq("transcription_lease_token", str(lease_token))
    )
    return bool(result.data)


def fail_speaking_response_transcription(
    *,
    response_id: UUID,
    lease_token: UUID,
    retryable: bool,
    error: str,
    next_attempt_at_iso: str | None,
) -> bool:
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses")
        .update(
            {
                "transcription_status": "retry_wait" if retryable else "failed",
                "transcription_error": error[:2000],
                "transcription_next_attempt_at": next_attempt_at_iso,
                "transcription_lease_token": None,
                "transcription_lease_expires_at": None,
            }
        )
        .eq("id", str(response_id))
        .eq("transcription_status", "processing")
        .eq("transcription_lease_token", str(lease_token))
    )
    return bool(result.data)


def reset_speaking_response_transcription(
    *,
    response_id: UUID,
    reason: str,
) -> bool:
    """Invalidate a completed snapshot when its source identity changed."""
    client = get_supabase()
    result = _exec(
        client.table("speaking_responses")
        .update(
            {
                "transcription_status": "queued",
                "transcription_error": reason[:2000],
                "transcription_attempts": 0,
                "transcription_next_attempt_at": None,
                "transcription_lease_token": None,
                "transcription_lease_expires_at": None,
            }
        )
        .eq("id", str(response_id))
        .eq("status", "confirmed")
    )
    return bool(result.data)


def transcription_progress(*, attempt_id: UUID) -> dict[str, int]:
    rows = list_speaking_responses(attempt_id=attempt_id)
    counts = {
        "total": len(rows),
        "queued": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
    }
    for row in rows:
        state = str(row.get("transcription_status") or "not_queued")
        if state in {"queued", "retry_wait", "not_queued"}:
            counts["queued"] += 1
        elif state in counts:
            counts[state] += 1
    return counts
