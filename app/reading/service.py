"""Business logic for the Reading module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.cache.hybrid_cache import get_json, set_json
from app.cache.mock_cache import invalidate_mock_progress_caches
from app.db.module_submit_bundle import persist_module_submit_bundle
from app.config import get_settings
from app.reading import repository as repo
from app.mock_catalog.constants import live_content_part
from app.reading.constants import READING_DURATION_MINUTES, READING_GRACE_SECONDS
from app.reading.evaluation import (
    build_skill_breakdown,
    calculate_reading_band,
    is_answer_correct,
    score_answers,
)
from app.reading.schemas import (
    AutosaveResponse,
    QuestionReviewItem,
    ReadingQuestion,
    ReadingQuestionsResponse,
    ReadingScoreReport,
    SkillBreakdownEntry,
    StartReadingResponse,
    SubmitReadingResponse,
)
from app.schemas.test_engine import TestSummary


def _is_dev() -> bool:
    return get_settings().app_env.strip().lower() == "development"


def _reading_duration_seconds(
    *, mock_test_id: UUID, mock_attempt_id: UUID | None
) -> int:
    if mock_attempt_id is not None:
        from app.services import mock_orchestrator_repository as mock_repo

        minutes = mock_repo.module_duration_minutes(
            mock_test_id=mock_test_id, module="reading"
        )
        if minutes:
            return minutes * 60
    return READING_DURATION_MINUTES * 60


def _reading_duration_minutes(
    *, mock_test_id: UUID, mock_attempt_id: UUID | None
) -> int:
    return _reading_duration_seconds(
        mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
    ) // 60


def _ensure_owner(attempt: dict[str, Any], user_id: UUID) -> None:
    if str(attempt.get("user_id")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this attempt.",
        )


def _content_part(*, mock_test_id: UUID, live_part: int | None) -> int | None:
    if live_part is None:
        return None
    return live_content_part(
        mock_test_id=str(mock_test_id), module="reading", live_part=live_part
    )


def _mock_reading_session_started_at(
    *,
    user_id: UUID,
    mock_test_id: UUID,
    mock_attempt_id: UUID,
    current_attempt: dict[str, Any],
) -> datetime:
    earliest = repo.earliest_reading_started_at(
        user_id=user_id,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
    )
    if earliest and earliest.get("started_at"):
        return _parse_started_at(earliest)
    return _parse_started_at(current_attempt)


def _parse_started_at(attempt: dict[str, Any]) -> datetime:
    raw = attempt.get("started_at")
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if isinstance(raw, datetime):
        return raw
    return datetime.now(UTC)


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


def _review_explanation(*, prompt: str, user_answer: str, correct: str | None, ok: bool) -> str:
    if ok:
        return "Your answer matches the passage."
    if correct:
        return f"The passage supports: {correct}."
    return f"Review the passage for: {prompt[:120]}…"


def _rows_to_reading_questions(
    *,
    mock_test_id: UUID,
    rows: list[dict],
    part: int | None,
) -> tuple[str | None, list[ReadingQuestion]]:
    passage_text: str | None = None
    questions: list[ReadingQuestion] = []
    offset = repo.display_offset_before_part(
        mock_test_id=mock_test_id, part=part or 1
    )
    for row in rows:
        if passage_text is None and row.get("passage_text"):
            passage_text = str(row["passage_text"])
        qn = int(row["question_number"])
        questions.append(
            ReadingQuestion(
                id=UUID(str(row["id"])),
                question_number=qn,
                display_number=offset + qn,
                question_type=str(row["question_type"]),
                prompt=str(row["prompt"]),
                options=row.get("options"),
                skill_tag=row.get("skill_tag"),
            )
        )
    return passage_text, questions


def _pack_session_content(
    *, mock_test_id: UUID, include_questions: bool, part: int | None = None
) -> tuple[TestSummary | None, str | None, list[ReadingQuestion]]:
    if not include_questions:
        return None, None, []
    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    content_part = _content_part(mock_test_id=mock_test_id, live_part=part)
    rows = repo.list_questions_public(mock_test_id, part=content_part)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No reading questions found for this mock test.",
        )
    passage_text, questions = _rows_to_reading_questions(
        mock_test_id=mock_test_id, rows=rows, part=part
    )
    test = TestSummary(
        id=UUID(str(test_row["id"])),
        title=str(test_row["title"]),
        description=test_row.get("description"),
    )
    return test, passage_text, questions


def start_attempt(
    *,
    mock_test_id: UUID,
    user_id: UUID,
    force_new: bool = False,
    include_questions: bool = True,
    part: int = 1,
    mock_attempt_id: UUID | None = None,
) -> StartReadingResponse:
    repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    if mock_attempt_id is not None:
        from app.services import mock_orchestrator

        repo.abandon_stale_reading_attempts(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            part=part,
        )
        mock_orchestrator.assert_module_unlocked(
            mock_attempt_id=mock_attempt_id,
            user_id=user_id,
            mock_test_id=mock_test_id,
            module="reading",
            part=part,
        )
    existing = repo.find_in_progress_reading_attempt(
        user_id=user_id,
        mock_test_id=mock_test_id,
        part=part,
        mock_attempt_id=mock_attempt_id,
    )
    if existing and mock_attempt_id is not None:
        existing_ma = existing.get("mock_attempt_id")
        if not existing_ma or str(existing_ma) != str(mock_attempt_id):
            repo.abandon_reading_attempt(attempt_id=UUID(str(existing["id"])))
            existing = None
    if existing and force_new:
        repo.abandon_reading_attempt(attempt_id=UUID(str(existing["id"])))
        existing = None

    if existing:
        started_at = (
            _mock_reading_session_started_at(
                user_id=user_id,
                mock_test_id=mock_test_id,
                mock_attempt_id=mock_attempt_id,
                current_attempt=existing,
            )
            if mock_attempt_id is not None
            else _parse_started_at(existing)
        )
        test, passage_text, questions = _pack_session_content(
            mock_test_id=mock_test_id,
            include_questions=include_questions,
            part=part,
        )
        response = StartReadingResponse(
            attempt_id=UUID(str(existing["id"])),
            started_at=started_at,
            server_time=datetime.now(UTC),
            status=str(existing.get("status", "in_progress")),
            duration_seconds=_reading_duration_seconds(
                mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
            ),
            resumed=True,
            test=test,
            passage_text=passage_text,
            questions=questions,
        )
        if mock_attempt_id is not None:
            invalidate_mock_progress_caches(
                user_id=user_id,
                mock_test_id=mock_test_id,
                mock_attempt_id=mock_attempt_id,
            )
        return response

    row = repo.insert_reading_attempt(
        user_id=user_id,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
        part=part,
    )
    started_at = (
        _mock_reading_session_started_at(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
            current_attempt=row,
        )
        if mock_attempt_id is not None
        else _parse_started_at(row)
    )
    test, passage_text, questions = _pack_session_content(
        mock_test_id=mock_test_id,
        include_questions=include_questions,
        part=part,
    )
    response = StartReadingResponse(
        attempt_id=UUID(str(row["id"])),
        started_at=started_at,
        server_time=datetime.now(UTC),
        status=str(row.get("status", "in_progress")),
        duration_seconds=_reading_duration_seconds(
            mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
        ),
        resumed=False,
        test=test,
        passage_text=passage_text,
        questions=questions,
    )
    if mock_attempt_id is not None:
        invalidate_mock_progress_caches(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
        )
    return response


def get_session_questions(
    *, mock_test_id: UUID, user_id: UUID, part: int | None = None
) -> ReadingQuestionsResponse:
    cache_key = f"reading_questions:{mock_test_id}:{part or 0}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        try:
            return ReadingQuestionsResponse.model_validate(cached)
        except Exception:
            pass

    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    content_part = _content_part(mock_test_id=mock_test_id, live_part=part)
    rows = repo.list_questions_public(mock_test_id, part=content_part)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No reading questions found for this mock test.",
        )

    in_progress = repo.find_in_progress_reading_attempt(
        user_id=user_id, mock_test_id=mock_test_id, part=part
    )
    if not in_progress:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Start a reading attempt before loading questions.",
        )

    passage_text, questions = _rows_to_reading_questions(
        mock_test_id=mock_test_id, rows=rows, part=part
    )
    mock_attempt_raw = in_progress.get("mock_attempt_id")
    mock_attempt_id = (
        UUID(str(mock_attempt_raw)) if mock_attempt_raw else None
    )

    response = ReadingQuestionsResponse(
        test=TestSummary(
            id=UUID(str(test_row["id"])),
            title=str(test_row["title"]),
            description=test_row.get("description"),
        ),
        passage_text=passage_text,
        questions=questions,
        duration_seconds=_reading_duration_seconds(
            mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
        ),
    )
    set_json(cache_key, response.model_dump(mode="json"), ttl_seconds=600)
    return response


def autosave_answer(
    *,
    attempt_id: UUID,
    user_id: UUID,
    question_id: UUID,
    user_answer: str,
) -> AutosaveResponse:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "reading":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a reading attempt.")
    if attempt.get("status") != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Attempt is not in progress.")

    mock_test_id = UUID(str(attempt["mock_test_id"]))
    if not repo.question_belongs_to(mock_test_id, question_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid question_id.")

    repo.upsert_answer(
        attempt_id=attempt_id,
        question_id=question_id,
        user_answer=user_answer.strip(),
    )
    return AutosaveResponse(
        question_id=question_id,
        saved_at=datetime.now(UTC),
    )


def submit_attempt(
    *,
    attempt_id: UUID,
    user_id: UUID,
    answers: list[dict[str, str]],
) -> SubmitReadingResponse:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "reading":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a reading attempt.")
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot be submitted (status={attempt.get('status')}).",
        )

    mock_test_id = UUID(str(attempt["mock_test_id"]))
    if not attempt.get("mock_attempt_id"):
        from app.services import mock_orchestrator

        in_prog = mock_orchestrator.get_in_progress(
            mock_test_id=mock_test_id, user_id=user_id
        )
        if in_prog is not None:
            repo.set_attempt_mock_attempt_id(
                attempt_id=attempt_id,
                mock_attempt_id=in_prog.mock_attempt_id,
            )
            attempt["mock_attempt_id"] = str(in_prog.mock_attempt_id)
    attempt_part = attempt.get("part")
    live_part = int(attempt_part) if attempt_part is not None else None
    content_part = _content_part(mock_test_id=mock_test_id, live_part=live_part)
    questions = repo.list_questions_for_scoring(mock_test_id, part=content_part)
    if not questions:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="No reading questions configured for this mock test.",
        )

    answers_by_qid: dict[str, str] = {}
    for item in answers:
        qid = str(item.get("question_id", "")).strip()
        if qid:
            answers_by_qid[qid] = str(item.get("user_answer", "")).strip()

    valid_ids = {str(q["id"]) for q in questions}
    unknown = [qid for qid in answers_by_qid if qid not in valid_ids]
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="One or more question_ids are invalid for this attempt.",
        )

    raw_score, total, scored_rows = score_answers(
        questions=questions,
        answers_by_qid=answers_by_qid,
    )

    now = datetime.now(UTC)
    started_at = _parse_started_at(attempt)
    mock_attempt_raw = attempt.get("mock_attempt_id")
    mock_attempt_id = UUID(str(mock_attempt_raw)) if mock_attempt_raw else None
    duration_min = _reading_duration_minutes(
        mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
    )
    late = now - started_at > timedelta(minutes=duration_min) + timedelta(
        seconds=READING_GRACE_SECONDS
    )

    band = calculate_reading_band(raw_score, total=total)
    breakdown = build_skill_breakdown(questions=questions, rows=scored_rows)

    completed = persist_module_submit_bundle(
        attempt_id=attempt_id,
        user_id=user_id,
        module="reading",
        completed_at=now,
        answer_rows=scored_rows,
        raw_score=raw_score,
        total_count=total,
        band=band,
        skill_breakdown=breakdown,
    )

    completed_raw = completed.get("completed_at") or now.isoformat()
    submitted_at = (
        datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
        if isinstance(completed_raw, str)
        else completed_raw
    )

    mock_next_module: str | None = None
    mock_next_part: int | None = None
    mock_reading_complete = False
    if attempt.get("mock_attempt_id"):
        from app.services import mock_orchestrator

        progress = mock_orchestrator.on_module_attempt_completed(
            test_attempt_id=attempt_id,
            user_id=user_id,
            attempt=completed,
        )
        if progress is not None:
            mock_next_module = progress.next_module
            mock_next_part = progress.next_part
            if progress.status == "completed" or progress.next_module != "reading":
                mock_reading_complete = True

    response = SubmitReadingResponse(
        attempt_id=attempt_id,
        status="completed",
        submitted_at=submitted_at,
        raw_score=raw_score,
        total_questions=total,
        band=band,
        late_submission=late,
        skill_breakdown=_to_breakdown_entries(breakdown),
        mock_next_module=mock_next_module,
        mock_next_part=mock_next_part,
        mock_reading_complete=mock_reading_complete,
    )
    if mock_attempt_id is not None:
        invalidate_mock_progress_caches(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
        )
    return response


def get_score_report(*, attempt_id: UUID, user_id: UUID) -> ReadingScoreReport:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "reading":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a reading attempt.")
    if attempt.get("status") != "completed":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Score report is not available yet.",
        )

    score = repo.get_module_score(attempt_id)
    if not score:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Score report not found.")

    started_at = _parse_started_at(attempt)
    completed_raw = attempt.get("completed_at")
    submitted_at = None
    late = False
    mock_test_id = UUID(str(attempt["mock_test_id"]))
    mock_attempt_raw = attempt.get("mock_attempt_id")
    mock_attempt_id = UUID(str(mock_attempt_raw)) if mock_attempt_raw else None
    duration_min = _reading_duration_minutes(
        mock_test_id=mock_test_id, mock_attempt_id=mock_attempt_id
    )
    if isinstance(completed_raw, str) and completed_raw:
        submitted_at = datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
        late = submitted_at - started_at > timedelta(
            minutes=duration_min,
            seconds=READING_GRACE_SECONDS,
        )

    raw_breakdown = score.get("skill_breakdown") or {}
    breakdown: dict[str, SkillBreakdownEntry] = {}
    for skill, v in raw_breakdown.items():
        if isinstance(v, dict):
            breakdown[str(skill)] = SkillBreakdownEntry(
                correct=int(v.get("correct", 0)),
                total=int(v.get("total", 0)),
                pct=float(v.get("pct", 0.0)),
            )

    mock_test_id = UUID(str(attempt["mock_test_id"]))
    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    answer_rows = repo.list_answers_for_attempt(attempt_id)
    answers_by_qid = {
        str(row["question_id"]): {
            "user_answer": str(row.get("user_answer") or ""),
            "is_correct": row.get("is_correct"),
        }
        for row in answer_rows
    }

    attempt_part = attempt.get("part")
    review_part = int(attempt_part) if attempt_part is not None else None
    review_items: list[QuestionReviewItem] = []
    for q in repo.list_questions_for_review(mock_test_id, part=review_part):
        qid = str(q["id"])
        ans = answers_by_qid.get(qid, {})
        user_answer = ans.get("user_answer", "")
        stored_correct = ans.get("is_correct")
        if stored_correct is None:
            correct_flag = is_answer_correct(user_answer, q.get("correct_answer"))
        else:
            correct_flag = bool(stored_correct)
        correct_display = str(q.get("correct_answer") or "—")
        review_items.append(
            QuestionReviewItem(
                question_id=UUID(qid),
                question_number=int(q["question_number"]),
                question_type=str(q.get("question_type") or ""),
                prompt=str(q.get("prompt") or ""),
                user_answer=user_answer,
                correct_answer=correct_display,
                is_correct=correct_flag,
                explanation=_review_explanation(
                    prompt=str(q.get("prompt") or ""),
                    user_answer=user_answer,
                    correct=q.get("correct_answer"),
                    ok=correct_flag,
                ),
            )
        )

    return ReadingScoreReport(
        attempt_id=attempt_id,
        status="completed",
        test_title=str(test_row.get("title") or ""),
        submitted_at=submitted_at,
        raw_score=int(score.get("raw_score") or score.get("correct_count") or 0),
        total_questions=int(score.get("total_count") or 0),
        band=float(score.get("band") or 0.0),
        late_submission=late,
        skill_breakdown=breakdown,
        questions=review_items,
    )
