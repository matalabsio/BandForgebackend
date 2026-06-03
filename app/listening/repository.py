"""Thin Supabase wrappers for the Listening module.

Keeps the service layer free of supabase-py specifics and makes
mocking trivial.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.db.supabase_client import execute_with_retry, get_supabase

QUESTION_PUBLIC_COLUMNS = (
    "id, mock_test_id, module, part, question_type, question_number, "
    "prompt, passage_text, audio_url, options, skill_tag"
)
QUESTION_SCORING_COLUMNS = "id, correct_answer, skill_tag, part"
QUESTION_REVIEW_COLUMNS = (
    "id, question_number, question_type, prompt, correct_answer, skill_tag"
)


def _exec(query):
    return execute_with_retry(query.execute)


def get_mock_test(mock_test_id: UUID, *, allow_unpublished: bool = False) -> dict[str, Any]:
    client = get_supabase()
    result = (
        client.table("mock_tests")
        .select("id, title, description, is_published")
        .eq("id", str(mock_test_id))
        .limit(1)
    )
    result = _exec(result)
    rows = result.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")
    row = rows[0]
    if not row.get("is_published") and not allow_unpublished:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock test not found.")
    return row


def count_questions_by_part(*, mock_test_id: UUID) -> dict[int, int]:
    """Part number → question count (for global Q1–40 display numbering)."""
    client = get_supabase()
    result = (
        client.table("questions")
        .select("part")
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "listening")
    )
    result = _exec(result)
    counts: dict[int, int] = {}
    for row in result.data or []:
        p = int(row["part"]) if row.get("part") is not None else 1
        counts[p] = counts.get(p, 0) + 1
    return counts


def part_display_offsets(*, mock_test_id: UUID) -> dict[int, int]:
    """Part number → global display offset (one count query for all parts)."""
    counts = count_questions_by_part(mock_test_id=mock_test_id)
    offsets: dict[int, int] = {}
    running = 0
    for p in sorted(counts.keys()):
        offsets[p] = running
        running += counts[p]
    return offsets


def display_offset_before_part(*, mock_test_id: UUID, part: int) -> int:
    return part_display_offsets(mock_test_id=mock_test_id).get(part, 0)


def list_questions_public(
    mock_test_id: UUID, *, part: int | None = None
) -> list[dict[str, Any]]:
    client = get_supabase()
    query = (
        client.table("questions")
        .select(QUESTION_PUBLIC_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "listening")
    )
    if part is not None:
        query = query.eq("part", part)
    result = _exec(query.order("part", desc=False).order("question_number"))
    return list(result.data or [])


def list_questions_for_scoring(
    mock_test_id: UUID, *, part: int | None = None
) -> list[dict[str, Any]]:
    client = get_supabase()
    query = (
        client.table("questions")
        .select(QUESTION_SCORING_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "listening")
    )
    if part is not None:
        query = query.eq("part", part)
    result = _exec(query.order("part", desc=False).order("question_number"))
    return list(result.data or [])


def earliest_listening_started_at(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID,
) -> dict[str, Any] | None:
    """Earliest listening attempt start for a mock session (shared 30-min clock)."""
    client = get_supabase()
    result = (
        client.table("test_attempts")
        .select("started_at")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(mock_test_id))
        .eq("mock_attempt_id", str(mock_attempt_id))
        .eq("module", "listening")
        .in_("status", ["in_progress", "completed"])
        .order("started_at")
        .limit(1)
    )
    result = _exec(result)
    rows = result.data or []
    return rows[0] if rows else None


def find_in_progress_listening_attempt(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    part: int | None = None,
    mock_attempt_id: UUID | None = None,
) -> dict[str, Any] | None:
    client = get_supabase()
    query = (
        client.table("test_attempts")
        .select("id, started_at, status, part, mock_attempt_id")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "listening")
        .eq("status", "in_progress")
    )
    if mock_attempt_id is not None:
        query = query.eq("mock_attempt_id", str(mock_attempt_id))
    if part is not None:
        query = query.eq("part", part)
    result = _exec(query.limit(1))
    rows = result.data or []
    return rows[0] if rows else None


def abandon_listening_attempt(*, attempt_id: UUID) -> None:
    client = get_supabase()
    _exec(client.table("test_attempts").update({"status": "abandoned"}).eq("id", str(attempt_id)))


def abandon_stale_listening_attempts(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID,
    part: int | None = None,
) -> None:
    """Abandon orphan or superseded in-progress listening rows for this mock session."""
    client = get_supabase()
    session_rows = list(
        (
            _exec(
                client.table("test_attempts")
                .select("id, part, status, mock_attempt_id")
                .eq("user_id", str(user_id))
                .eq("mock_test_id", str(mock_test_id))
                .eq("module", "listening")
                .eq("mock_attempt_id", str(mock_attempt_id))
            )
        ).data
        or []
    )
    done_parts = {
        int(row["part"])
        for row in session_rows
        if row.get("status") == "completed" and row.get("part") is not None
    }

    query = (
        client.table("test_attempts")
        .select("id, mock_attempt_id, part")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "listening")
        .eq("status", "in_progress")
    )
    if part is not None:
        query = query.eq("part", part)
    rows = list((_exec(query)).data or [])
    for row in rows:
        existing_ma = row.get("mock_attempt_id")
        row_part = row.get("part")
        if not existing_ma or str(existing_ma) != str(mock_attempt_id):
            abandon_listening_attempt(attempt_id=UUID(str(row["id"])))
            continue
        if row_part is not None and int(row_part) in done_parts:
            abandon_listening_attempt(attempt_id=UUID(str(row["id"])))


def insert_listening_attempt(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID | None = None,
    part: int | None = None,
) -> dict[str, Any]:
    client = get_supabase()
    payload: dict[str, Any] = {
        "user_id": str(user_id),
        "mock_test_id": str(mock_test_id),
        "module": "listening",
        "status": "in_progress",
    }
    if mock_attempt_id is not None:
        payload["mock_attempt_id"] = str(mock_attempt_id)
    if part is not None:
        payload["part"] = part
    insert = _exec(client.table("test_attempts").insert(payload))
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
        .select(
            "id, user_id, mock_test_id, module, status, started_at, completed_at, "
            "part, mock_attempt_id"
        )
        .eq("id", str(attempt_id))
        .limit(1)
    )
    result = _exec(result)
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
    )
    result = _exec(result)
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
    _exec(client.table("answers").upsert(payload, on_conflict="attempt_id,question_id"))


def mark_attempt_completed(attempt_id: UUID, *, completed_at_iso: str) -> dict[str, Any]:
    client = get_supabase()
    updated = (
        client.table("test_attempts")
        .update({"status": "completed", "completed_at": completed_at_iso})
        .eq("id", str(attempt_id))
    )
    updated = _exec(updated)
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
    _exec(
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
        )
    )


def list_questions_for_review(
    mock_test_id: UUID, *, part: int | None = None
) -> list[dict[str, Any]]:
    client = get_supabase()
    query = (
        client.table("questions")
        .select(QUESTION_REVIEW_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "listening")
    )
    if part is not None:
        query = query.eq("part", part)
    result = _exec(query.order("part", desc=False).order("question_number"))
    return list(result.data or [])


def list_answers_for_attempt(attempt_id: UUID) -> list[dict[str, Any]]:
    client = get_supabase()
    result = (
        client.table("answers")
        .select("question_id, user_answer, is_correct")
        .eq("attempt_id", str(attempt_id))
    )
    result = _exec(result)
    return list(result.data or [])


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
    )
    result = _exec(result)
    rows = result.data or []
    return rows[0] if rows else None
