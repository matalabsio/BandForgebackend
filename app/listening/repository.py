"""Thin Supabase wrappers for the Listening module.

Keeps the service layer free of supabase-py specifics and makes
mocking trivial.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.db.supabase_client import get_supabase

QUESTION_PUBLIC_COLUMNS = (
    "id, mock_test_id, module, part, question_type, question_number, "
    "prompt, passage_text, audio_url, options, skill_tag"
)
QUESTION_SCORING_COLUMNS = "id, correct_answer, skill_tag, part"


def get_mock_test(mock_test_id: UUID, *, allow_unpublished: bool = False) -> dict[str, Any]:
    client = get_supabase()
    result = (
        client.table("mock_tests")
        .select("id, title, description, is_published")
        .eq("id", str(mock_test_id))
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")
    row = rows[0]
    if not row.get("is_published") and not allow_unpublished:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")
    return row


def list_questions_public(mock_test_id: UUID) -> list[dict[str, Any]]:
    client = get_supabase()
    result = (
        client.table("questions")
        .select(QUESTION_PUBLIC_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "listening")
        .order("part", desc=False)
        .order("question_number")
        .execute()
    )
    return list(result.data or [])


def list_questions_for_scoring(mock_test_id: UUID) -> list[dict[str, Any]]:
    client = get_supabase()
    result = (
        client.table("questions")
        .select(QUESTION_SCORING_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "listening")
        .order("part", desc=False)
        .order("question_number")
        .execute()
    )
    return list(result.data or [])


def find_in_progress_listening_attempt(*, user_id: UUID, mock_test_id: UUID) -> dict[str, Any] | None:
    client = get_supabase()
    result = (
        client.table("test_attempts")
        .select("id, started_at, status")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "listening")
        .eq("status", "in_progress")
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def insert_listening_attempt(*, user_id: UUID, mock_test_id: UUID) -> dict[str, Any]:
    client = get_supabase()
    insert = (
        client.table("test_attempts")
        .insert(
            {
                "user_id": str(user_id),
                "mock_test_id": str(mock_test_id),
                "module": "listening",
                "status": "in_progress",
            }
        )
        .execute()
    )
    if not insert.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to create listening attempt.",
        )
    return insert.data[0]


def get_attempt(attempt_id: UUID) -> dict[str, Any]:
    client = get_supabase()
    result = (
        client.table("test_attempts")
        .select("id, user_id, mock_test_id, module, status, started_at, completed_at")
        .eq("id", str(attempt_id))
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test attempt not found.")
    return rows[0]


def question_belongs_to(mock_test_id: UUID, question_id: UUID) -> bool:
    client = get_supabase()
    result = (
        client.table("questions")
        .select("id")
        .eq("id", str(question_id))
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "listening")
        .limit(1)
        .execute()
    )
    return bool(result.data)


def upsert_answer(*, attempt_id: UUID, question_id: UUID, user_answer: str) -> None:
    client = get_supabase()
    client.table("answers").upsert(
        {
            "attempt_id": str(attempt_id),
            "question_id": str(question_id),
            "user_answer": user_answer,
        },
        on_conflict="attempt_id,question_id",
    ).execute()


def upsert_scored_answers(*, attempt_id: UUID, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    client = get_supabase()
    payload = [
        {
            "attempt_id": str(attempt_id),
            "question_id": row["question_id"],
            "user_answer": row.get("user_answer", ""),
            "is_correct": bool(row.get("is_correct")),
        }
        for row in rows
    ]
    client.table("answers").upsert(payload, on_conflict="attempt_id,question_id").execute()


def mark_attempt_completed(attempt_id: UUID, *, completed_at_iso: str) -> dict[str, Any]:
    client = get_supabase()
    updated = (
        client.table("test_attempts")
        .update({"status": "completed", "completed_at": completed_at_iso})
        .eq("id", str(attempt_id))
        .execute()
    )
    if not updated.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to mark attempt as completed.",
        )
    return updated.data[0]


def upsert_module_score(
    *,
    attempt_id: UUID,
    raw_score: int,
    total: int,
    band: float,
    skill_breakdown: dict[str, dict[str, float | int]],
) -> None:
    client = get_supabase()
    client.table("module_scores").upsert(
        {
            "attempt_id": str(attempt_id),
            "module": "listening",
            "raw_score": raw_score,
            "correct_count": raw_score,
            "total_count": total,
            "band": band,
            "skill_breakdown": skill_breakdown,
        },
        on_conflict="attempt_id,module",
    ).execute()


def get_module_score(attempt_id: UUID) -> dict[str, Any] | None:
    client = get_supabase()
    result = (
        client.table("module_scores")
        .select(
            "attempt_id, module, raw_score, correct_count, total_count, band, "
            "skill_breakdown, scored_at"
        )
        .eq("attempt_id", str(attempt_id))
        .eq("module", "listening")
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None
