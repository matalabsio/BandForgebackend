"""Day 2 test engine: questions, start attempt, submit answers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.config import get_settings
from app.db.supabase_client import get_supabase
from app.schemas.test_engine import (
    QuestionPublic,
    QuestionsResponse,
    StartAttemptResponse,
    SubmitAnswersResponse,
    TestModule,
    TestSummary,
)
from app.mock_catalog.constants import PUBLISHED_FULL_MOCK_IDS
from app.reading.constants import READING_DURATION_MINUTES
from app.storage.r2 import generate_signed_url, parse_r2_object_url

LATE_SUBMISSION_MINUTES = 65
R2_PRESIGN_EXPIRY = 10800  # 3 hours

QUESTION_PUBLIC_COLUMNS = (
    "id, mock_test_id, module, question_type, question_number, "
    "prompt, passage_text, audio_url, options, skill_tag"
)


class TestEngineError(HTTPException):
    pass


def _is_dev() -> bool:
    return get_settings().app_env.strip().lower() == "development"


def _presign_audio(stored: str | None) -> str | None:
    if not stored or not stored.strip():
        return None
    key = parse_r2_object_url(stored.strip()) or stored.strip().lstrip("/")
    try:
        return generate_signed_url(key, expiry=R2_PRESIGN_EXPIRY)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Listening audio is not available: {exc}",
        ) from exc


def _get_mock_test_row(mock_test_id: UUID) -> dict[str, Any]:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mock test not found.",
        )
    row = rows[0]
    if not row.get("is_published") and not _is_dev():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mock test not found.",
        )
    return row


def list_published_tests(*, include_unpublished: bool = False) -> list[TestSummary]:
    """Return dashboard-visible full mocks (catalog_number slots)."""
    from app.mock_catalog.catalog import list_catalog_mock_rows

    rows: list[dict[str, Any]] = list_catalog_mock_rows(
        include_unpublished=include_unpublished
    )
    client = get_supabase()

    listening_counts: dict[str, int] = {}
    reading_counts: dict[str, int] = {}
    if rows:
        mock_ids = [str(row["id"]) for row in rows]
        q_result = (
            client.table("questions")
            .select("mock_test_id, module")
            .in_("mock_test_id", mock_ids)
            .in_("module", ["listening", "reading"])
            .execute()
        )
        for q_row in q_result.data or []:
            mid = str(q_row["mock_test_id"])
            mod = str(q_row.get("module") or "")
            if mod == "listening":
                listening_counts[mid] = listening_counts.get(mid, 0) + 1
            elif mod == "reading":
                reading_counts[mid] = reading_counts.get(mid, 0) + 1

    from app.services import mock_orchestrator_repository as mor

    module_durations: dict[str, dict[str, int]] = {}
    for mid in [str(row["id"]) for row in rows]:
        try:
            for m in mor.list_mock_modules(UUID(mid)):
                module_durations.setdefault(mid, {})[str(m["module"])] = int(
                    m["duration_minutes"]
                )
        except Exception:
            module_durations[mid] = {"listening": 30, "reading": READING_DURATION_MINUTES}

    summaries = [
        TestSummary(
            id=UUID(str(row["id"])),
            title=str(row["title"]),
            description=row.get("description"),
            listening_question_count=listening_counts.get(str(row["id"])),
            listening_duration_minutes=module_durations.get(str(row["id"]), {}).get(
                "listening", 30
            ),
            reading_question_count=reading_counts.get(str(row["id"])),
            reading_duration_minutes=module_durations.get(str(row["id"]), {}).get(
                "reading", READING_DURATION_MINUTES
            ),
        )
        for row in rows
    ]
    summaries.sort(key=lambda t: t.title.lower())
    return summaries


def _assert_active_mock_attempt(*, mock_test_id: UUID, user_id: UUID) -> None:
    """Require an in-progress mock attempt before serving exam content."""
    client = get_supabase()
    result = (
        client.table("mock_attempts")
        .select("id")
        .eq("mock_test_id", str(mock_test_id))
        .eq("user_id", str(user_id))
        .eq("status", "in_progress")
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found.",
        )


def get_questions(
    mock_test_id: UUID,
    module: TestModule,
    *,
    user_id: UUID,
) -> QuestionsResponse:
    _assert_active_mock_attempt(mock_test_id=mock_test_id, user_id=user_id)
    test_row = _get_mock_test_row(mock_test_id)
    client = get_supabase()
    result = (
        client.table("questions")
        .select(QUESTION_PUBLIC_COLUMNS)
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", module)
        .order("question_number")
        .execute()
    )
    rows: list[dict[str, Any]] = result.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No questions found for module '{module}'.",
        )

    passage_text: str | None = None
    audio_urls: list[str] = []
    seen_audio: set[str] = set()
    questions: list[QuestionPublic] = []

    for row in rows:
        if module == "reading":
            if passage_text is None and row.get("passage_text"):
                passage_text = row["passage_text"]
        elif module == "listening":
            raw_audio = row.get("audio_url")
            if raw_audio:
                signed = _presign_audio(raw_audio)
                if signed and signed not in seen_audio:
                    seen_audio.add(signed)
                    audio_urls.append(signed)

        questions.append(
            QuestionPublic(
                id=UUID(str(row["id"])),
                question_number=int(row["question_number"]),
                question_type=str(row["question_type"]),
                prompt=str(row["prompt"]),
                options=row.get("options"),
                skill_tag=row.get("skill_tag"),
            )
        )

    return QuestionsResponse(
        test=TestSummary(
            id=UUID(str(test_row["id"])),
            title=str(test_row["title"]),
            description=test_row.get("description"),
        ),
        module=module,
        passage_text=passage_text,
        audio_urls=audio_urls,
        questions=questions,
    )


def _parse_started_at(row: dict[str, Any]) -> datetime:
    started_at = row.get("started_at")
    if isinstance(started_at, str):
        return datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    if isinstance(started_at, datetime):
        return started_at
    return datetime.now(UTC)


def _find_in_progress_attempt(
    client: Any,
    *,
    user_id: UUID,
    mock_test_id: UUID,
    module: TestModule,
) -> dict[str, Any] | None:
    result = (
        client.table("test_attempts")
        .select("id, started_at, status, module")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", module)
        .eq("status", "in_progress")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def start_attempt(
    mock_test_id: UUID,
    module: TestModule,
    *,
    user_id: UUID,
    force_new: bool = False,
) -> StartAttemptResponse:
    """Start a new attempt or resume the latest in-progress one for this mock + module."""
    _get_mock_test_row(mock_test_id)
    client = get_supabase()

    existing = _find_in_progress_attempt(
        client,
        user_id=user_id,
        mock_test_id=mock_test_id,
        module=module,
    )

    if existing and not force_new:
        return StartAttemptResponse(
            attempt_id=UUID(str(existing["id"])),
            started_at=_parse_started_at(existing),
            status=str(existing.get("status", "in_progress")),
            module=module,
            resumed=True,
        )

    if existing and force_new:
        client.table("test_attempts").update({"status": "abandoned"}).eq(
            "id", str(existing["id"])
        ).execute()

    insert = (
        client.table("test_attempts")
        .insert(
            {
                "user_id": str(user_id),
                "mock_test_id": str(mock_test_id),
                "module": module,
                "status": "in_progress",
            }
        )
        .execute()
    )
    if not insert.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create test attempt.",
        )
    row = insert.data[0]

    return StartAttemptResponse(
        attempt_id=UUID(str(row["id"])),
        started_at=_parse_started_at(row),
        status=str(row.get("status", "in_progress")),
        module=module,
        resumed=False,
    )


def _load_attempt(attempt_id: UUID) -> dict[str, Any]:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test attempt not found.",
        )
    return rows[0]


def submit_answers(
    attempt_id: UUID,
    *,
    user_id: UUID,
    answers: list[dict[str, str]],
) -> SubmitAnswersResponse:
    attempt = _load_attempt(attempt_id)
    if str(attempt["user_id"]) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this attempt.",
        )
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot be submitted (status={attempt.get('status')}).",
        )

    mock_test_id = attempt.get("mock_test_id")
    module = attempt.get("module")
    if not mock_test_id or not module:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt is missing mock_test_id or module.",
        )

    question_ids = [a["question_id"] for a in answers]
    client = get_supabase()
    valid = (
        client.table("questions")
        .select("id")
        .eq("mock_test_id", str(mock_test_id))
        .eq("module", str(module))
        .in_("id", question_ids)
        .execute()
    )
    valid_ids = {str(r["id"]) for r in (valid.data or [])}
    invalid = [qid for qid in question_ids if qid not in valid_ids]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more question_ids are invalid for this attempt.",
        )

    payload = [
        {
            "attempt_id": str(attempt_id),
            "question_id": item["question_id"],
            "user_answer": item["user_answer"],
        }
        for item in answers
    ]
    client.table("answers").upsert(
        payload,
        on_conflict="attempt_id,question_id",
    ).execute()

    now = datetime.now(UTC)
    started_raw = attempt.get("started_at")
    if isinstance(started_raw, str):
        started_at = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
    else:
        started_at = started_raw or now
    late = now - started_at > timedelta(minutes=LATE_SUBMISSION_MINUTES)

    updated = (
        client.table("test_attempts")
        .update({"status": "completed", "completed_at": now.isoformat()})
        .eq("id", str(attempt_id))
        .execute()
    )
    row = (updated.data or [attempt])[0]
    completed_raw = row.get("completed_at") or now.isoformat()
    if isinstance(completed_raw, str):
        submitted_at = datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
    else:
        submitted_at = completed_raw

    return SubmitAnswersResponse(
        attempt_id=attempt_id,
        status="completed",
        submitted_at=submitted_at,
        answer_count=len(answers),
        late_submission=late,
    )
