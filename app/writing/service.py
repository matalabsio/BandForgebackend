"""Business logic for the Writing module (save for review, no evaluation)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.cache.hybrid_cache import get_json, set_json
from app.config import get_settings
from app.schemas.test_engine import TestSummary
from app.services.mock_progress_timing import MockProgressTiming
from app.writing import repository as repo
from app.writing.ai_evaluator import ai_evaluation_available, evaluate_mock_essay
from app.writing.constants import (
    TASK1_DURATION_MINUTES,
    TASK2_DURATION_MINUTES,
    WRITING_GRACE_SECONDS,
)
from app.writing.evaluation import calculate_writing_band, min_words_for_part
from app.writing.schemas import (
    AutosaveResponse,
    StartWritingResponse,
    SubmitWritingResponse,
    WritingPendingResponse,
    WritingReviewResponse,
    WritingSessionTaskSummary,
    WritingTaskQuestion,
)
from app.writing.timing import (
    WritingAutosaveTiming,
    WritingStartTiming,
    WritingSubmitTiming,
)


def _is_dev() -> bool:
    return get_settings().app_env.strip().lower() == "development"


def _duration_seconds_for_part(part: int) -> int:
    minutes = TASK1_DURATION_MINUTES if part == 1 else TASK2_DURATION_MINUTES
    return minutes * 60


def _word_count(text: str) -> int:
    stripped = text.strip()
    return len(stripped.split()) if stripped else 0


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(coro)
    finally:
        new_loop.close()


def _session_tasks(
    attempt: dict[str, Any],
    *,
    user_id: UUID,
) -> list[WritingSessionTaskSummary]:
    part = int(attempt.get("part") or 1)
    attempt_id = UUID(str(attempt["id"]))
    mock_attempt_raw = attempt.get("mock_attempt_id")
    if not mock_attempt_raw:
        review = repo.get_writing_review_for_attempt(attempt_id)
        if not review:
            return []
        human_band = review.get("human_band")
        return [
            WritingSessionTaskSummary(
                attempt_id=attempt_id,
                part=part,
                human_band=float(human_band) if human_band is not None else None,
                review_status=str(review.get("status") or "pending"),
            )
        ]

    mock_attempt_id = UUID(str(mock_attempt_raw))
    rows = repo.list_completed_writing_attempts_for_session(
        user_id=user_id,
        mock_attempt_id=mock_attempt_id,
    )
    tasks: list[WritingSessionTaskSummary] = []
    for row in rows:
        aid = UUID(str(row["id"]))
        review = repo.get_writing_review_for_attempt(aid)
        human_band = review.get("human_band") if review else None
        tasks.append(
            WritingSessionTaskSummary(
                attempt_id=aid,
                part=int(row.get("part") or 1),
                human_band=float(human_band) if human_band is not None else None,
                review_status=str((review or {}).get("status") or "pending"),
            )
        )
    return tasks


def _ensure_owner(attempt: dict[str, Any], user_id: UUID) -> None:
    from app.security.ownership import ensure_owner_or_not_found

    ensure_owner_or_not_found(attempt, user_id)


def _parse_started_at(attempt: dict[str, Any]) -> datetime:
    raw = attempt.get("started_at")
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if isinstance(raw, datetime):
        return raw
    return datetime.now(UTC)


WRITING_TASK_CACHE_TTL_SEC = 1800


def _writing_task_cache_key(mock_test_id: UUID, part: int) -> str:
    return f"writing_task:{mock_test_id}:{part}"


def _row_to_task(row: dict[str, Any]) -> WritingTaskQuestion:
    opts = row.get("options")
    return WritingTaskQuestion(
        id=UUID(str(row["id"])),
        question_number=int(row.get("question_number") or 1),
        question_type=str(row.get("question_type") or "task2"),
        prompt=str(row.get("prompt") or ""),
        part=int(row.get("part") or 1),
        options=opts if isinstance(opts, dict) else None,
    )


def _pack_task(
    *,
    mock_test_id: UUID,
    part: int,
    timing: WritingStartTiming | None = None,
) -> tuple[TestSummary, WritingTaskQuestion]:
    cache_key = _writing_task_cache_key(mock_test_id, part)
    cached = get_json(cache_key)
    if isinstance(cached, dict) and cached.get("task_row"):
        t_task = perf_counter()
        test = TestSummary(
            id=UUID(str(cached["test_id"])),
            title=str(cached.get("test_title") or ""),
            description=cached.get("test_description"),
        )
        task = _row_to_task(cached["task_row"])
        if timing is not None:
            timing.task_source = "cache"
            timing.task_ms = round((perf_counter() - t_task) * 1000)
        return test, task

    t_prompt = perf_counter()
    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    if timing is not None:
        timing.prompt_ms = round((perf_counter() - t_prompt) * 1000)
    t_task = perf_counter()
    rows = repo.list_questions_for_part(mock_test_id=mock_test_id, part=part)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No writing task found for part {part}.",
        )
    test = TestSummary(
        id=UUID(str(test_row["id"])),
        title=str(test_row["title"]),
        description=test_row.get("description"),
    )
    task = _row_to_task(rows[0])
    set_json(
        cache_key,
        {
            "test_id": str(test_row["id"]),
            "test_title": test_row.get("title"),
            "test_description": test_row.get("description"),
            "task_row": rows[0],
        },
        ttl_seconds=WRITING_TASK_CACHE_TTL_SEC,
    )
    if timing is not None:
        timing.task_source = "db"
        timing.task_ms = round((perf_counter() - t_task) * 1000)
    return test, task


def start_attempt(
    *,
    mock_test_id: UUID,
    user_id: UUID,
    part: int,
    force_new: bool = False,
    mock_attempt_id: UUID | None = None,
    timing: WritingStartTiming | None = None,
) -> StartWritingResponse:
    t_request = perf_counter()
    if part not in (1, 2):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Writing part must be 1 or 2.")

    if mock_attempt_id is not None:
        from app.cache.mock_cache import read_unlock_snapshot
        from app.services.mock_orchestrator import assert_module_unlocked

        if timing is not None:
            timing.unlock_source = (
                "cache"
                if read_unlock_snapshot(
                    mock_attempt_id=mock_attempt_id, user_id=user_id
                )
                else "db"
            )
        t_unlock = perf_counter()
        assert_module_unlocked(
            mock_attempt_id=mock_attempt_id,
            user_id=user_id,
            mock_test_id=mock_test_id,
            module="writing",
            part=part,
        )
        if timing is not None:
            timing.unlock_ms = round((perf_counter() - t_unlock) * 1000)

    t_attempt = perf_counter()
    existing = repo.find_in_progress_writing_attempt(
        user_id=user_id,
        mock_test_id=mock_test_id,
        part=part,
        mock_attempt_id=mock_attempt_id,
    )
    if existing and mock_attempt_id is not None:
        existing_ma = existing.get("mock_attempt_id")
        if not existing_ma or str(existing_ma) != str(mock_attempt_id):
            repo.abandon_writing_attempt(attempt_id=UUID(str(existing["id"])))
            existing = None
    if existing and force_new:
        repo.abandon_writing_attempt(attempt_id=UUID(str(existing["id"])))
        existing = None

    if existing:
        if timing is not None:
            timing.attempt_ms = round((perf_counter() - t_attempt) * 1000)
        test, task = _pack_task(
            mock_test_id=mock_test_id, part=part, timing=timing
        )
        aid = UUID(str(existing["id"]))
        t_saved = perf_counter()
        saved_row = repo.get_answer_for_attempt(
            attempt_id=aid, question_id=task.id
        )
        if timing is not None:
            timing.task_ms += round((perf_counter() - t_saved) * 1000)
        response = StartWritingResponse(
            attempt_id=aid,
            started_at=_parse_started_at(existing),
            server_time=datetime.now(UTC),
            status=str(existing.get("status", "in_progress")),
            part=part,
            duration_seconds=_duration_seconds_for_part(part),
            resumed=True,
            test=test,
            task=task,
            saved_answer=str((saved_row or {}).get("user_answer") or "") or None,
        )
        if timing is not None:
            timing.duration_ms = round((perf_counter() - t_request) * 1000)
        return response

    row = repo.insert_writing_attempt(
        user_id=user_id,
        mock_test_id=mock_test_id,
        mock_attempt_id=mock_attempt_id,
        part=part,
    )
    if timing is not None:
        timing.attempt_ms = round((perf_counter() - t_attempt) * 1000)
    test, task = _pack_task(mock_test_id=mock_test_id, part=part, timing=timing)
    response = StartWritingResponse(
        attempt_id=UUID(str(row["id"])),
        started_at=_parse_started_at(row),
        server_time=datetime.now(UTC),
        status=str(row.get("status", "in_progress")),
        part=part,
        duration_seconds=_duration_seconds_for_part(part),
        resumed=False,
        test=test,
        task=task,
    )
    if timing is not None:
        timing.duration_ms = round((perf_counter() - t_request) * 1000)
    return response


def autosave_answer(
    *,
    attempt_id: UUID,
    user_id: UUID,
    question_id: UUID,
    user_answer: str,
    timing: WritingAutosaveTiming | None = None,
) -> AutosaveResponse:
    t_request = perf_counter()
    t0 = perf_counter()
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if timing is not None:
        timing.attempt_ms = round((perf_counter() - t0) * 1000)
    if attempt.get("module") != "writing":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a writing attempt.")
    if attempt.get("status") != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Attempt is not in progress.")

    mock_test_id = UUID(str(attempt["mock_test_id"]))
    part = int(attempt.get("part") or 1)
    t0 = perf_counter()
    if not repo.question_belongs_to(mock_test_id, question_id, part=part):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid question_id.")
    if timing is not None:
        timing.validate_ms = round((perf_counter() - t0) * 1000)

    t0 = perf_counter()
    repo.upsert_answer(
        attempt_id=attempt_id,
        question_id=question_id,
        user_answer=user_answer,
    )
    if timing is not None:
        timing.autosave_ms = round((perf_counter() - t0) * 1000)
    response = AutosaveResponse(
        question_id=question_id,
        saved_at=datetime.now(UTC),
    )
    if timing is not None:
        timing.duration_ms = round((perf_counter() - t_request) * 1000)
    return response


def submit_attempt(
    *,
    attempt_id: UUID,
    user_id: UUID,
    answers: list[dict[str, str]],
    timing: WritingSubmitTiming | None = None,
) -> SubmitWritingResponse:
    t_request = perf_counter()
    t0 = perf_counter()
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if timing is not None:
        timing.attempt_ms = round((perf_counter() - t0) * 1000)
    if attempt.get("module") != "writing":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a writing attempt.")
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Attempt cannot be submitted (status={attempt.get('status')}).",
        )

    mock_test_id = UUID(str(attempt["mock_test_id"]))
    part = int(attempt.get("part") or 1)
    t0 = perf_counter()
    rows = repo.list_questions_for_part(mock_test_id=mock_test_id, part=part)
    if timing is not None:
        timing.task_ms = round((perf_counter() - t0) * 1000)
    if not rows:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="No writing task configured for this part.",
        )
    question = rows[0]
    question_id = UUID(str(question["id"]))

    answers_by_qid: dict[str, str] = {}
    for item in answers:
        qid = str(item.get("question_id", "")).strip()
        if qid:
            answers_by_qid[qid] = str(item.get("user_answer", ""))

    essay = answers_by_qid.get(str(question_id), "").strip()
    if not essay:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Essay cannot be empty.",
        )

    t0 = perf_counter()
    words = _word_count(essay)
    estimate_band = calculate_writing_band(words=words, part=part)
    if timing is not None:
        timing.scoring_compute_ms = round((perf_counter() - t0) * 1000)

    now = datetime.now(UTC)
    t0 = perf_counter()
    repo.upsert_answer(
        attempt_id=attempt_id,
        question_id=question_id,
        user_answer=essay,
    )
    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    part_label = f"Task {part}"
    submission_meta = {
        "part": part,
        "part_label": part_label,
        "prompt_title": str(question.get("question_type") or "writing"),
        "question": str(question.get("prompt") or ""),
        "essay": essay,
        "word_count": words,
        "mock_title": test_row.get("title"),
    }
    repo.insert_writing_review(
        attempt_id=attempt_id,
        submission_meta=submission_meta,
        ai_scores={
            "word_count_estimate": estimate_band,
            "word_count": words,
        },
    )
    completed = repo.mark_attempt_completed(
        attempt_id, completed_at_iso=now.isoformat()
    )
    if timing is not None:
        timing.rpc_bundle_ms = round((perf_counter() - t0) * 1000)
    completed_raw = completed.get("completed_at") or now.isoformat()
    submitted_at = (
        datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
        if isinstance(completed_raw, str)
        else completed_raw
    )

    next_part: int | None = 2 if part == 1 else None
    mock_next_module: str | None = None
    mock_next_part: int | None = None
    mock_writing_complete = False

    mock_attempt_raw = attempt.get("mock_attempt_id")
    if mock_attempt_raw:
        from app.services import mock_orchestrator

        progress_timing = MockProgressTiming() if timing is not None else None
        if timing is not None:
            timing.progress_timing = progress_timing
        progress = mock_orchestrator.on_module_attempt_completed(
            test_attempt_id=attempt_id,
            user_id=user_id,
            attempt=completed,
            timing=progress_timing,
        )
        if timing is not None and progress_timing is not None:
            timing.progress_ms = progress_timing.progress_ms
        if progress is not None:
            mock_next_module = progress.next_module
            mock_next_part = progress.next_part
            if progress.status == "completed" or progress.next_module != "writing":
                mock_writing_complete = True
            elif progress.next_module == "writing" and progress.next_part:
                next_part = progress.next_part

    response = SubmitWritingResponse(
        attempt_id=attempt_id,
        status="completed",
        submitted_at=submitted_at,
        part=part,
        word_count=words,
        band=None,
        min_words=min_words_for_part(part),
        saved_for_review=True,
        next_part=next_part,
        mock_next_module=mock_next_module,
        mock_next_part=mock_next_part,
        mock_writing_complete=mock_writing_complete,
    )
    if timing is not None:
        timing.duration_ms = round((perf_counter() - t_request) * 1000)
    return response


def get_review(*, attempt_id: UUID, user_id: UUID) -> WritingReviewResponse:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "writing":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a writing attempt.")
    if attempt.get("status") != "completed":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Review is not available until the task is submitted.",
        )

    mock_test_id = UUID(str(attempt["mock_test_id"]))
    part = int(attempt.get("part") or 1)
    rows = repo.list_questions_for_part(mock_test_id=mock_test_id, part=part)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found.")

    question = rows[0]
    question_id = UUID(str(question["id"]))
    answer_row = repo.get_answer_for_attempt(
        attempt_id=attempt_id, question_id=question_id
    )
    essay = str((answer_row or {}).get("user_answer") or "")

    test_row = repo.get_mock_test(mock_test_id, allow_unpublished=_is_dev())
    completed_raw = attempt.get("completed_at")
    submitted_at = None
    if completed_raw:
        submitted_at = (
            datetime.fromisoformat(str(completed_raw).replace("Z", "+00:00"))
            if isinstance(completed_raw, str)
            else completed_raw
        )

    words = _word_count(essay)
    review_row = repo.get_writing_review_for_attempt(attempt_id)
    score_row = repo.get_module_score(attempt_id)
    saved_for_review = review_row is not None
    ai_available = ai_evaluation_available()
    ai_band = None
    band = None
    band_source = "none"
    ai_scores: dict[str, Any] = {}
    review_id: UUID | None = None
    if review_row:
        raw_ai_scores = review_row.get("ai_scores")
        ai_scores = raw_ai_scores if isinstance(raw_ai_scores, dict) else {}
        if review_row.get("id"):
            review_id = UUID(str(review_row["id"]))
        ai_band_raw = ai_scores.get("ai_band")
        if ai_band_raw is not None:
            try:
                ai_band = float(ai_band_raw)
            except (TypeError, ValueError):
                ai_band = None
    ai_criteria_raw = ai_scores.get("criteria") if isinstance(ai_scores, dict) else {}
    ai_criteria = (
        {
            str(k): float(v)
            for k, v in ai_criteria_raw.items()
            if isinstance(ai_criteria_raw, dict) and isinstance(v, (int, float))
        }
        if isinstance(ai_criteria_raw, dict)
        else {}
    )
    ai_strengths = (
        [str(item) for item in ai_scores.get("strengths", [])]
        if isinstance(ai_scores, dict)
        else []
    )
    ai_improvements = (
        [str(item) for item in ai_scores.get("improvements", [])]
        if isinstance(ai_scores, dict)
        else []
    )
    ai_model_name = (
        str(ai_scores.get("model_name"))
        if isinstance(ai_scores, dict) and ai_scores.get("model_name")
        else None
    )

    if (
        review_row
        and ai_band is None
        and ai_available
        and essay.strip()
        and review_id is not None
    ):
        evaluation = None
        try:
            evaluation = _run_async(
                evaluate_mock_essay(
                    part=part,
                    question=str(question.get("prompt") or ""),
                    essay=essay,
                )
            )
        except Exception:
            evaluation = None
        if isinstance(evaluation, dict):
            merged = {**ai_scores, **evaluation}
            repo.update_writing_review_ai_scores(review_id=review_id, ai_scores=merged)
            ai_scores = merged
            ai_band_raw = ai_scores.get("ai_band")
            if ai_band_raw is not None:
                try:
                    ai_band = float(ai_band_raw)
                except (TypeError, ValueError):
                    ai_band = None
            criteria_raw = ai_scores.get("criteria")
            if isinstance(criteria_raw, dict):
                ai_criteria = {
                    str(k): float(v)
                    for k, v in criteria_raw.items()
                    if isinstance(v, (int, float))
                }
            ai_strengths = [str(item) for item in ai_scores.get("strengths", [])]
            ai_improvements = [str(item) for item in ai_scores.get("improvements", [])]
            ai_model_name = (
                str(ai_scores.get("model_name")) if ai_scores.get("model_name") else None
            )

    if score_row and score_row.get("band") is not None:
        band = float(score_row["band"])
        band_source = "module_score"
    elif review_row and review_row.get("human_band") is not None:
        band = float(review_row["human_band"])
        band_source = "human"
    elif ai_band is not None:
        band = ai_band
        band_source = "ai"
    elif review_row:
        if ai_scores.get("word_count_estimate") is not None:
            try:
                band = float(ai_scores["word_count_estimate"])
                band_source = "word_count_estimate"
            except (TypeError, ValueError):
                band = None
                band_source = "none"

    opts = question.get("options")
    return WritingReviewResponse(
        attempt_id=attempt_id,
        status="completed",
        part=part,
        test_title=str(test_row.get("title")),
        question_type=str(question.get("question_type") or "task2"),
        prompt=str(question.get("prompt") or ""),
        options=opts if isinstance(opts, dict) else None,
        user_answer=essay,
        word_count=words,
        band=band,
        ai_band=ai_band,
        ai_available=ai_available,
        band_source=band_source,
        ai_criteria=ai_criteria,
        ai_strengths=ai_strengths,
        ai_improvements=ai_improvements,
        ai_model_name=ai_model_name,
        min_words=min_words_for_part(part),
        submitted_at=submitted_at,
        saved_for_review=saved_for_review and band is None,
        session_tasks=_session_tasks(attempt, user_id=user_id),
    )


def get_pending_status(
    *,
    attempt_id: UUID,
    user_id: UUID,
) -> WritingPendingResponse:
    attempt = repo.get_attempt(attempt_id)
    _ensure_owner(attempt, user_id)
    if attempt.get("module") != "writing":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not a writing attempt.")

    review = repo.get_writing_review_for_attempt(attempt_id)
    if not review:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No writing submission found.")

    review_status = str(review.get("status") or "pending")
    human_band = review.get("human_band")
    band_val = float(human_band) if human_band is not None else None

    if review_status == "completed" and band_val is not None:
        message = f"Your Writing band is {band_val:.1f}."
    else:
        message = (
            "Your Writing score is coming soon. A certified examiner is reviewing "
            "your essay — you will receive your band within 24 hours."
        )

    completed_raw = attempt.get("completed_at")
    submitted_at = None
    if completed_raw:
        submitted_at = (
            datetime.fromisoformat(str(completed_raw).replace("Z", "+00:00"))
            if isinstance(completed_raw, str)
            else completed_raw
        )

    return WritingPendingResponse(
        attempt_id=attempt_id,
        status=str(attempt.get("status") or "completed"),
        review_status=review_status,
        human_band=band_val,
        submitted_at=submitted_at,
        message=message,
        session_tasks=_session_tasks(attempt, user_id=user_id),
    )
