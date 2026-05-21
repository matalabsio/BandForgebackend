"""Business logic for the Listening module.

Routes stay thin; this layer enforces ownership, presigns audio,
calls the synchronous evaluator, and persists module_scores.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.config import get_settings
from app.listening import repository as repo
from app.listening.constants import (
    LISTENING_AUDIO_PRESIGN_EXPIRY_SECONDS,
    LISTENING_DURATION_MINUTES,
    LISTENING_GRACE_SECONDS,
)
from app.listening.evaluation import (
    build_skill_breakdown,
    calculate_band,
    score_answers,
)
from app.listening.schemas import (
    AutosaveResponse,
    ListeningPart,
    ListeningQuestion,
    ListeningQuestionsResponse,
    ListeningScoreReport,
    SkillBreakdownEntry,
    StartListeningResponse,
    SubmitListeningResponse,
)
from app.schemas.test_engine import TestSummary
from app.storage.r2 import generate_signed_url, parse_r2_object_url


PART_META: dict[int, dict[str, str]] = {
    1: {
        "title": "Part 1 — Social Dialogue",
        "context": "Everyday social conversation between two speakers.",
        "common_question_type": "form_completion",
    },
    2: {
        "title": "Part 2 — Social Monologue",
        "context": "One speaker in an everyday social setting (tour, broadcast, briefing).",
        "common_question_type": "mcq / map_labeling",
    },
    3: {
        "title": "Part 3 — Academic Seminar",
        "context": "Academic discussion involving two to four speakers.",
        "common_question_type": "mcq / matching",
    },
    4: {
        "title": "Part 4 — Academic Lecture",
        "context": "Single speaker delivering a university-level lecture.",
        "common_question_type": "note_completion",
    },
}


def _is_dev() -> bool:
    return get_settings().app_env.strip().lower() == "development"


def _presign_audio(stored: str | None) -> str | None:
    if not stored or not stored.strip():
        return None
    key = parse_r2_object_url(stored.strip()) or stored.strip().lstrip("/")
    try:
        return generate_signed_url(
            key,
            expiry=LISTENING_AUDIO_PRESIGN_EXPIRY_SECONDS,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Listening audio is not available: {exc}",
        ) from exc


def _ensure_owner(attempt: dict[str, Any], user_id: UUID) -> None:
    if str(attempt.get("user_id")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this attempt.",
        )


def _parse_started_at(attempt: dict[str, Any]) -> datetime:
    raw = attempt.get("started_at")
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if isinstance(raw, datetime):
        return raw
    return datetime.now(UTC)


def start_attempt(*, mock_test_id: UUID, user_id: UUID) -> StartListeningResponse:
    """Create a new listening attempt, or resume the user's existing in-progress one."""
    repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    existing = repo.find_in_progress_listening_attempt(
        user_id=user_id, mock_test_id=mock_test_id
    )
    if existing:
        started_at = _parse_started_at(existing)
        return StartListeningResponse(
            attempt_id=UUID(str(existing["id"])),
            started_at=started_at,
            server_time=datetime.now(UTC),
            status=str(existing.get("status", "in_progress")),
            duration_seconds=LISTENING_DURATION_MINUTES * 60,
        )

    row = repo.insert_listening_attempt(user_id=user_id, mock_test_id=mock_test_id)
    started_at = _parse_started_at(row)
    return StartListeningResponse(
        attempt_id=UUID(str(row["id"])),
        started_at=started_at,
        server_time=datetime.now(UTC),
        status=str(row.get("status", "in_progress")),
        duration_seconds=LISTENING_DURATION_MINUTES * 60,
    )


def get_session_questions(
    *, mock_test_id: UUID, user_id: UUID  # noqa: ARG001 — reserved for per-user gates
) -> ListeningQuestionsResponse:
    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    rows = repo.list_questions_public(mock_test_id)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No listening questions found for this mock test.",
        )

    grouped: dict[int, list[ListeningQuestion]] = {1: [], 2: [], 3: [], 4: []}
    for row in rows:
        part_raw = row.get("part")
        part = int(part_raw) if part_raw is not None else 1
        if part not in grouped:
            grouped[part] = []
        raw_audio = row.get("audio_url")
        signed_audio = _presign_audio(raw_audio) if raw_audio else None
        instructions = row.get("passage_text") or None  # reused as per-question instructions
        grouped[part].append(
            ListeningQuestion(
                id=UUID(str(row["id"])),
                part=part,  # type: ignore[arg-type]
                question_number=int(row["question_number"]),
                question_type=str(row["question_type"]),
                prompt=str(row["prompt"]),
                instructions=instructions,
                options=row.get("options"),
                skill_tag=row.get("skill_tag"),
                audio_url=signed_audio,
            )
        )

    parts: list[ListeningPart] = []
    for part_num in sorted(grouped.keys()):
        items = grouped[part_num]
        if not items:
            continue
        meta = PART_META.get(part_num, {})
        parts.append(
            ListeningPart(
                part=part_num,  # type: ignore[arg-type]
                title=meta.get("title", f"Part {part_num}"),
                context=meta.get("context", ""),
                common_question_type=meta.get("common_question_type", ""),
                questions=items,
            )
        )

    return ListeningQuestionsResponse(
        test=TestSummary(
            id=UUID(str(test_row["id"])),
            title=str(test_row["title"]),
            description=test_row.get("description"),
        ),
        parts=parts,
        duration_seconds=LISTENING_DURATION_MINUTES * 60,
    )


def autosave_answer(
    *,
    attempt_id: UUID,
    user_id: UUID,
    question_id: UUID,
    user_answer: str,
) -> AutosaveResponse:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "listening":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt is not a listening attempt.",
        )
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot be edited (status={attempt.get('status')}).",
        )
    if not repo.question_belongs_to(UUID(str(attempt["mock_test_id"])), question_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question does not belong to this listening attempt.",
        )
    repo.upsert_answer(
        attempt_id=attempt_id,
        question_id=question_id,
        user_answer=user_answer,
    )
    return AutosaveResponse(
        ok=True,
        question_id=question_id,
        saved_at=datetime.now(UTC),
    )


def _to_breakdown_entries(
    raw: dict[str, dict[str, float | int]],
) -> dict[str, SkillBreakdownEntry]:
    return {
        skill: SkillBreakdownEntry(
            correct=int(v.get("correct", 0)),
            total=int(v.get("total", 0)),
            pct=float(v.get("pct", 0.0)),
        )
        for skill, v in raw.items()
    }


def submit_attempt(
    *,
    attempt_id: UUID,
    user_id: UUID,
    answers: list[dict[str, str]],
) -> SubmitListeningResponse:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "listening":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt is not a listening attempt.",
        )
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot be submitted (status={attempt.get('status')}).",
        )

    mock_test_id = UUID(str(attempt["mock_test_id"]))
    questions = repo.list_questions_for_scoring(mock_test_id)
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No listening questions are configured for this mock test.",
        )

    answers_by_qid: dict[str, str] = {}
    for item in answers:
        qid = str(item.get("question_id", "")).strip()
        if not qid:
            continue
        answers_by_qid[qid] = str(item.get("user_answer", "")).strip()

    valid_ids = {str(q["id"]) for q in questions}
    unknown = [qid for qid in answers_by_qid if qid not in valid_ids]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more question_ids are invalid for this attempt.",
        )

    raw_score, total, scored_rows = score_answers(
        questions=questions,
        answers_by_qid=answers_by_qid,
    )
    repo.upsert_scored_answers(attempt_id=attempt_id, rows=scored_rows)

    now = datetime.now(UTC)
    started_at = _parse_started_at(attempt)
    grace = timedelta(seconds=LISTENING_GRACE_SECONDS)
    late = now - started_at > timedelta(minutes=LISTENING_DURATION_MINUTES) + grace

    band = calculate_band(raw_score, total=total)
    breakdown = build_skill_breakdown(questions=questions, rows=scored_rows)

    completed = repo.mark_attempt_completed(attempt_id, completed_at_iso=now.isoformat())
    repo.upsert_module_score(
        attempt_id=attempt_id,
        raw_score=raw_score,
        total=total,
        band=band,
        skill_breakdown=breakdown,
    )

    completed_raw = completed.get("completed_at") or now.isoformat()
    submitted_at = (
        datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
        if isinstance(completed_raw, str)
        else completed_raw
    )

    return SubmitListeningResponse(
        attempt_id=attempt_id,
        status="completed",
        submitted_at=submitted_at,
        raw_score=raw_score,
        total_questions=total,
        band=band,
        late_submission=late,
        skill_breakdown=_to_breakdown_entries(breakdown),
    )


def get_score_report(
    *,
    attempt_id: UUID,
    user_id: UUID,
) -> ListeningScoreReport:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "listening":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attempt is not a listening attempt.",
        )
    if attempt.get("status") != "completed":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Score report is not available yet.",
        )
    score = repo.get_module_score(attempt_id)
    if not score:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Score report not found.",
        )

    started_at = _parse_started_at(attempt)
    completed_raw = attempt.get("completed_at")
    submitted_at = None
    late = False
    if isinstance(completed_raw, str) and completed_raw:
        submitted_at = datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
        late = submitted_at - started_at > timedelta(
            minutes=LISTENING_DURATION_MINUTES,
            seconds=LISTENING_GRACE_SECONDS,
        )

    raw_breakdown = score.get("skill_breakdown") or {}
    breakdown: dict[str, SkillBreakdownEntry] = {}
    for skill, v in raw_breakdown.items():
        if not isinstance(v, dict):
            continue
        breakdown[str(skill)] = SkillBreakdownEntry(
            correct=int(v.get("correct", 0)),
            total=int(v.get("total", 0)),
            pct=float(v.get("pct", 0.0)),
        )

    return ListeningScoreReport(
        attempt_id=attempt_id,
        status="completed",
        submitted_at=submitted_at,
        raw_score=int(score.get("raw_score") or score.get("correct_count") or 0),
        total_questions=int(score.get("total_count") or 0),
        band=float(score.get("band") or 0.0),
        late_submission=late,
        skill_breakdown=breakdown,
    )
