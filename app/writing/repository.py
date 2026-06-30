"""Supabase accessors for the Writing module."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.db.supabase_client import execute_with_retry, get_supabase

QUESTION_PUBLIC_COLUMNS = (
    "id, mock_test_id, module, question_type, question_number, part, prompt, options"
)


def _exec(query):
    """Retry transient Supabase disconnects (common on autosave during mocks)."""
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
        .eq("module", "writing")
        .eq("part", part)
        .order("question_number")
    )
    return list(result.data or [])


def find_in_progress_writing_attempt(
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
        .eq("module", "writing")
        .eq("status", "in_progress")
        .eq("part", part)
    )
    if mock_attempt_id is not None:
        query = query.eq("mock_attempt_id", str(mock_attempt_id))
    result = _exec(query.limit(1))
    rows = result.data or []
    return rows[0] if rows else None


def abandon_writing_attempt(*, attempt_id: UUID) -> None:
    client = get_supabase()
    _exec(
        client.table("test_attempts").update({"status": "abandoned"}).eq(
            "id", str(attempt_id)
        )
    )


def insert_writing_attempt(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID | None = None,
    part: int,
) -> dict[str, Any]:
    client = get_supabase()
    payload: dict[str, Any] = {
        "user_id": str(user_id),
        "mock_test_id": str(mock_test_id),
        "module": "writing",
        "status": "in_progress",
        "part": part,
    }
    if mock_attempt_id is not None:
        payload["mock_attempt_id"] = str(mock_attempt_id)
    insert = _exec(client.table("test_attempts").insert(payload))
    if not insert.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to create writing attempt.",
        )
    return insert.data[0]


def get_attempt(attempt_id: UUID) -> dict[str, Any]:
    client = get_supabase()
    result = _exec(
        client.table("test_attempts")
        .select(
            "id, user_id, mock_test_id, module, status, started_at, completed_at, "
            "part, mock_attempt_id"
        )
        .eq("id", str(attempt_id))
        .limit(1)
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test attempt not found.")
    return rows[0]


def question_belongs_to(
    mock_test_id: UUID, question_id: UUID, *, part: int | None = None
) -> bool:
    client = get_supabase()
    query = (
        client.table("questions")
        .select("id")
        .eq("id", str(question_id))
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "writing")
    )
    if part is not None:
        query = query.eq("part", part)
    result = _exec(query.limit(1))
    return bool(result.data)


def upsert_answer(*, attempt_id: UUID, question_id: UUID, user_answer: str) -> None:
    client = get_supabase()
    _exec(
        client.table("answers").upsert(
            {
                "attempt_id": str(attempt_id),
                "question_id": str(question_id),
                "user_answer": user_answer,
            },
            on_conflict="attempt_id,question_id",
        )
    )


def get_answer_for_attempt(
    *, attempt_id: UUID, question_id: UUID
) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.table("answers")
        .select("user_answer, answered_at")
        .eq("attempt_id", str(attempt_id))
        .eq("question_id", str(question_id))
        .limit(1)
    )
    rows = result.data or []
    return rows[0] if rows else None


def get_module_score(attempt_id: UUID) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.table("module_scores")
        .select("attempt_id, module, band, raw_score, total_count, skill_breakdown")
        .eq("attempt_id", str(attempt_id))
        .eq("module", "writing")
        .limit(1)
    )
    rows = result.data or []
    return rows[0] if rows else None


def get_writing_review_for_attempt(attempt_id: UUID) -> dict[str, Any] | None:
    client = get_supabase()
    result = _exec(
        client.table("writing_reviews")
        .select("id, status, human_band, created_at, reviewer_notes")
        .eq("attempt_id", str(attempt_id))
        .order("created_at", desc=True)
        .limit(1)
    )
    rows = result.data or []
    return rows[0] if rows else None


def insert_writing_review(
    *,
    attempt_id: UUID,
    submission_meta: dict[str, Any],
    ai_scores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client = get_supabase()
    payload: dict[str, Any] = {
        "attempt_id": str(attempt_id),
        "status": "pending",
        "submission_meta": submission_meta,
    }
    if ai_scores is not None:
        payload["ai_scores"] = ai_scores
    insert = _exec(client.table("writing_reviews").insert(payload))
    if not insert.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to queue writing review.",
        )
    return insert.data[0]


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
            "Failed to complete writing attempt.",
        )
    return updated.data[0]


def has_completed_part(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    part: int,
    mock_attempt_id: UUID | None = None,
) -> bool:
    client = get_supabase()
    query = (
        client.table("test_attempts")
        .select("id")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "writing")
        .eq("part", part)
        .eq("status", "completed")
    )
    if mock_attempt_id is not None:
        query = query.eq("mock_attempt_id", str(mock_attempt_id))
    result = _exec(query.limit(1))
    return bool(result.data)
