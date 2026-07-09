"""Supabase accessors for the Reading module."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.db.supabase_client import get_supabase
from app.perf.timing import timed_supabase

QUESTION_PUBLIC_COLUMNS = (
    "id, mock_test_id, module, question_type, question_number, "
    "prompt, passage_text, options, skill_tag"
)
QUESTION_SCORING_COLUMNS = "id, correct_answer, skill_tag, question_type"
QUESTION_REVIEW_COLUMNS = (
    "id, question_number, question_type, prompt, correct_answer, skill_tag"
)


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


def distinct_question_parts(*, mock_test_id: UUID) -> list[int]:
    """Sorted passage numbers (1..n) for reading under this mock."""
    client = get_supabase()
    result = (
        client.table("questions")
        .select("part")
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "reading")
        .execute()
    )
    parts: set[int] = set()
    for row in result.data or []:
        p = row.get("part")
        parts.add(int(p) if p is not None else 1)
    return sorted(parts) if parts else [1]


def count_questions_by_part(*, mock_test_id: UUID) -> dict[int, int]:
    """Single query: passage number → question count (IELTS display offset)."""
    client = get_supabase()
    result = (
        client.table("questions")
        .select("part")
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "reading")
        .execute()
    )
    counts: dict[int, int] = {}
    for row in result.data or []:
        p = int(row["part"]) if row.get("part") is not None else 1
        counts[p] = counts.get(p, 0) + 1
    return counts


def display_offset_before_part(*, mock_test_id: UUID, part: int) -> int:
    """Global question index offset across live reading passages."""
    from app.mock_catalog.constants import MODULE_LIVE_PARTS, live_content_part

    counts = count_questions_by_part(mock_test_id=mock_test_id)
    live_parts = MODULE_LIVE_PARTS.get(str(mock_test_id), {}).get("reading", (part,))
    offset = 0
    for p in live_parts:
        if p >= part:
            break
        cp = live_content_part(
            mock_test_id=str(mock_test_id), module="reading", live_part=p
        )
        offset += counts.get(cp, 0)
    return offset


def earliest_reading_started_at(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID,
) -> dict[str, Any] | None:
    """Earliest reading attempt start for a mock session (shared clock)."""
    client = get_supabase()
    result = (
        client.table("test_attempts")
        .select("started_at")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(mock_test_id))
        .eq("mock_attempt_id", str(mock_attempt_id))
        .eq("module", "reading")
        .in_("status", ["in_progress", "completed"])
        .order("started_at")
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def list_questions_public(
    mock_test_id: UUID, *, part: int | None = None
) -> list[dict[str, Any]]:
    client = get_supabase()
    query = (
        client.table("questions")
        .select(QUESTION_PUBLIC_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "reading")
    )
    if part is not None:
        query = query.eq("part", part)
    result = query.order("part", desc=False).order("question_number").execute()
    return list(result.data or [])


def list_questions_for_scoring(
    mock_test_id: UUID, *, part: int | None = None
) -> list[dict[str, Any]]:
    client = get_supabase()
    query = (
        client.table("questions")
        .select(QUESTION_SCORING_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "reading")
    )
    if part is not None:
        query = query.eq("part", part)
    result = query.order("part", desc=False).order("question_number").execute()
    return list(result.data or [])


def find_in_progress_reading_attempt(
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
        .eq("module", "reading")
        .eq("status", "in_progress")
    )
    if mock_attempt_id is not None:
        query = query.eq("mock_attempt_id", str(mock_attempt_id))
    if part is not None:
        query = query.eq("part", part)
    result = query.limit(1).execute()
    rows = result.data or []
    return rows[0] if rows else None


def abandon_reading_attempt(*, attempt_id: UUID) -> None:
    client = get_supabase()
    client.table("test_attempts").update({"status": "abandoned"}).eq(
        "id", str(attempt_id)
    ).execute()


def abandon_stale_reading_attempts(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID,
    part: int | None = None,
) -> None:
    """Abandon orphan or superseded in-progress reading rows for this mock session."""
    client = get_supabase()
    session_rows = list(
        (
            client.table("test_attempts")
            .select("id, part, status, mock_attempt_id")
            .eq("user_id", str(user_id))
            .eq("mock_test_id", str(mock_test_id))
            .eq("module", "reading")
            .eq("mock_attempt_id", str(mock_attempt_id))
            .execute()
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
        .eq("module", "reading")
        .eq("status", "in_progress")
    )
    if part is not None:
        query = query.eq("part", part)
    rows = list((query.execute()).data or [])
    for row in rows:
        existing_ma = row.get("mock_attempt_id")
        row_part = row.get("part")
        if not existing_ma or str(existing_ma) != str(mock_attempt_id):
            abandon_reading_attempt(attempt_id=UUID(str(row["id"])))
            continue
        if row_part is not None and int(row_part) in done_parts:
            abandon_reading_attempt(attempt_id=UUID(str(row["id"])))


def set_attempt_mock_attempt_id(
    *, attempt_id: UUID, mock_attempt_id: UUID
) -> None:
    client = get_supabase()
    client.table("test_attempts").update(
        {"mock_attempt_id": str(mock_attempt_id)}
    ).eq("id", str(attempt_id)).execute()


def insert_reading_attempt(
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
        "module": "reading",
        "status": "in_progress",
    }
    if mock_attempt_id is not None:
        payload["mock_attempt_id"] = str(mock_attempt_id)
    if part is not None:
        payload["part"] = part
    insert = client.table("test_attempts").insert(payload).execute()
    if not insert.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to create reading attempt.",
        )
    return insert.data[0]


def get_attempt(attempt_id: UUID) -> dict[str, Any]:
    def _run() -> dict[str, Any]:
        client = get_supabase()
        result = (
            client.table("test_attempts")
            .select(
                "id, user_id, mock_test_id, module, status, started_at, completed_at, "
                "part, mock_attempt_id"
            )
            .eq("id", str(attempt_id))
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Test attempt not found.")
        return rows[0]

    return timed_supabase("supabase.test_attempts.select", _run)


def question_belongs_to(mock_test_id: UUID, question_id: UUID) -> bool:
    def _run() -> bool:
        client = get_supabase()
        result = (
            client.table("questions")
            .select("id")
            .eq("id", str(question_id))
            .eq("mock_test_id", str(mock_test_id))
            .eq("module", "reading")
            .limit(1)
            .execute()
        )
        return bool(result.data)

    return timed_supabase("supabase.questions.select", _run)


def upsert_answer(*, attempt_id: UUID, question_id: UUID, user_answer: str) -> None:
    def _run() -> None:
        client = get_supabase()
        client.table("answers").upsert(
            {
                "attempt_id": str(attempt_id),
                "question_id": str(question_id),
                "user_answer": user_answer,
            },
            on_conflict="attempt_id,question_id",
        ).execute()

    timed_supabase("supabase.answers.upsert", _run)


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
            "module": "reading",
            "raw_score": raw_score,
            "correct_count": raw_score,
            "total_count": total,
            "band": band,
            "skill_breakdown": skill_breakdown,
        },
        on_conflict="attempt_id,module",
    ).execute()


def list_questions_for_review(
    mock_test_id: UUID, *, part: int | None = None
) -> list[dict[str, Any]]:
    client = get_supabase()
    query = (
        client.table("questions")
        .select(QUESTION_REVIEW_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", "reading")
    )
    if part is not None:
        query = query.eq("part", part)
    result = query.order("question_number").execute()
    return list(result.data or [])


def list_answers_for_attempt(attempt_id: UUID) -> list[dict[str, Any]]:
    client = get_supabase()
    result = (
        client.table("answers")
        .select("question_id, user_answer, is_correct")
        .eq("attempt_id", str(attempt_id))
        .execute()
    )
    return list(result.data or [])


def list_answers_map_for_attempt(attempt_id: UUID) -> dict[str, str]:
    rows = list_answers_for_attempt(attempt_id)
    out: dict[str, str] = {}
    for row in rows:
        qid = str(row.get("question_id") or "").strip()
        if not qid:
            continue
        out[qid] = str(row.get("user_answer") or "")
    return out


def get_module_score(attempt_id: UUID) -> dict[str, Any] | None:
    client = get_supabase()
    result = (
        client.table("module_scores")
        .select(
            "attempt_id, module, raw_score, correct_count, total_count, band, "
            "skill_breakdown, scored_at"
        )
        .eq("attempt_id", str(attempt_id))
        .eq("module", "reading")
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None
