"""Business logic for the Writing module (submit + background AI evaluation)."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID
import threading

from fastapi import BackgroundTasks, HTTPException, status

from app.cache.hybrid_cache import get_json, set_json
from app.config import get_settings
from app.diagnostic.evaluation_schemas import (
    GrammarMistake,
    SpellingMistake,
    StrongSpan,
    VocabularyHighlight,
)
from app.schemas.test_engine import TestSummary
from app.services.mock_progress_timing import MockProgressTiming
from app.writing import repository as repo
from app.writing.ai_evaluator import (
    AI_STATUS_COMPLETE,
    AI_STATUS_FAILED,
    AI_STATUS_PENDING,
    AI_STATUS_STUB,
    ai_evaluation_available,
    run_writing_evaluation,
)
from app.writing.constants import (
    TASK1_DURATION_MINUTES,
    TASK2_DURATION_MINUTES,
    WRITING_GRACE_SECONDS,
)
from app.writing.evaluation import calculate_writing_band, min_words_for_part
from app.writing.eval_utils import visual_description_from_task_options
from app.writing.providers.constants import PROVIDER_NAME_ANTHROPIC_CLAUDE, PROVIDER_NAME_GROQ
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


def _parse_mistakes(
    ai_scores: dict[str, Any],
    key: str,
    model: type[SpellingMistake] | type[GrammarMistake],
) -> list[SpellingMistake] | list[GrammarMistake]:
    raw = ai_scores.get(key) or []
    if not isinstance(raw, list):
        return []
    out: list[Any] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(model.model_validate(item))
            except Exception:
                continue
    return out


def _parse_vocabulary_highlights(ai_scores: dict[str, Any]) -> list[VocabularyHighlight]:
    raw = ai_scores.get("vocabulary_highlights") or []
    if not isinstance(raw, list):
        return []
    out: list[VocabularyHighlight] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(VocabularyHighlight.model_validate(item))
            except Exception:
                continue
    return out[:6]


def _parse_strong_spans(ai_scores: dict[str, Any]) -> list[StrongSpan]:
    raw = ai_scores.get("strong_spans") or []
    if not isinstance(raw, list):
        return []
    out: list[StrongSpan] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(StrongSpan.model_validate(item))
            except Exception:
                continue
    return out[:4]


def _parse_confidence(ai_scores: dict[str, Any]) -> float | None:
    if "confidence" not in ai_scores:
        return None
    raw = ai_scores.get("confidence")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return max(0.0, min(1.0, value))


def _parse_next_band_advice(ai_scores: dict[str, Any]) -> str:
    raw = ai_scores.get("next_band_advice")
    return str(raw).strip() if raw else ""


def _ai_provider_label(ai_scores: dict[str, Any]) -> str | None:
    used = ai_scores.get("provider_used")
    if used == PROVIDER_NAME_ANTHROPIC_CLAUDE:
        return "claude"
    if used == PROVIDER_NAME_GROQ:
        return "groq"
    return str(used) if used else None


def _ai_status_from_scores(ai_scores: dict[str, Any] | None) -> str | None:
    if not isinstance(ai_scores, dict) or not ai_scores.get("status"):
        return None
    return str(ai_scores["status"])


def _ai_band_from_scores(ai_scores: dict[str, Any] | None) -> float | None:
    if not isinstance(ai_scores, dict):
        return None
    raw = ai_scores.get("ai_band")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _session_task_from_review(
    *,
    attempt_id: UUID,
    part: int,
    review: dict[str, Any] | None,
) -> WritingSessionTaskSummary:
    ai_scores = (review or {}).get("ai_scores") if review else None
    human_band = review.get("human_band") if review else None
    return WritingSessionTaskSummary(
        attempt_id=attempt_id,
        part=part,
        human_band=float(human_band) if human_band is not None else None,
        review_status=str((review or {}).get("status") or "pending"),
        ai_status=_ai_status_from_scores(ai_scores if isinstance(ai_scores, dict) else None),
        ai_band=_ai_band_from_scores(ai_scores if isinstance(ai_scores, dict) else None),
    )


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
        return [_session_task_from_review(attempt_id=attempt_id, part=part, review=review)]

    mock_attempt_id = UUID(str(mock_attempt_raw))
    rows = repo.list_completed_writing_attempts_for_session(
        user_id=user_id,
        mock_attempt_id=mock_attempt_id,
    )
    tasks: list[WritingSessionTaskSummary] = []
    for row in rows:
        aid = UUID(str(row["id"]))
        review = repo.get_writing_review_for_attempt(aid)
        tasks.append(
            _session_task_from_review(
                attempt_id=aid,
                part=int(row.get("part") or 1),
                review=review,
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
    background_tasks: BackgroundTasks | None = None,
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
    options = question.get("options") if isinstance(question.get("options"), dict) else {}
    visual_description = visual_description_from_task_options(options, part=part)
    submission_meta = {
        "part": part,
        "part_label": part_label,
        "prompt_title": str(question.get("question_type") or "writing"),
        "question": str(question.get("prompt") or ""),
        "essay": essay,
        "word_count": words,
        "mock_title": test_row.get("title"),
        "visual_description": visual_description,
    }
    review_row = repo.insert_writing_review(
        attempt_id=attempt_id,
        submission_meta=submission_meta,
        ai_scores={
            "status": AI_STATUS_PENDING,
            "word_count_estimate": estimate_band,
            "word_count": words,
        },
    )
    review_id = UUID(str(review_row["id"]))
    if background_tasks is not None:
        background_tasks.add_task(run_writing_evaluation, review_id)
    else:
        run_writing_evaluation(review_id)
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
        ai_band = _ai_band_from_scores(ai_scores)

    ai_status = _ai_status_from_scores(ai_scores)
    # Safety net: re-enqueue in a daemon thread if still pending and stale (>2 min).
    if (
        review_id is not None
        and ai_status == AI_STATUS_PENDING
        and review_row
        and review_row.get("created_at")
    ):
        created_raw = review_row.get("created_at")
        try:
            created_at = (
                datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
                if not isinstance(created_raw, datetime)
                else created_raw
            )
            age_sec = (datetime.now(UTC) - created_at.astimezone(UTC)).total_seconds()
            if age_sec > 120:
                threading.Thread(
                    target=run_writing_evaluation,
                    args=(review_id,),
                    daemon=True,
                    name=f"writing-eval-retry-{review_id}",
                ).start()
        except Exception:
            pass

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
    ai_provider = _ai_provider_label(ai_scores) if isinstance(ai_scores, dict) else None
    spelling_mistakes = (
        _parse_mistakes(ai_scores, "spelling_mistakes", SpellingMistake)
        if isinstance(ai_scores, dict)
        else []
    )
    grammar_mistakes = (
        _parse_mistakes(ai_scores, "grammar_mistakes", GrammarMistake)
        if isinstance(ai_scores, dict)
        else []
    )
    next_band_advice = (
        _parse_next_band_advice(ai_scores) if isinstance(ai_scores, dict) else ""
    )
    confidence = _parse_confidence(ai_scores) if isinstance(ai_scores, dict) else None
    vocabulary_highlights = (
        _parse_vocabulary_highlights(ai_scores) if isinstance(ai_scores, dict) else []
    )
    strong_spans = (
        _parse_strong_spans(ai_scores) if isinstance(ai_scores, dict) else []
    )

    if score_row and score_row.get("band") is not None:
        band = float(score_row["band"])
        band_source = "module_score"
    elif review_row and review_row.get("human_band") is not None:
        band = float(review_row["human_band"])
        band_source = "human"
    elif ai_band is not None and ai_status in (AI_STATUS_COMPLETE, AI_STATUS_STUB):
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

    human_verified = band_source == "human"
    reviewer_notes: str | None = None
    if review_row and review_row.get("reviewer_notes"):
        reviewer_notes = str(review_row["reviewer_notes"])

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
        ai_status=ai_status,
        band_source=band_source,
        human_verified=human_verified,
        reviewer_notes=reviewer_notes,
        ai_criteria=ai_criteria,
        ai_strengths=ai_strengths,
        ai_improvements=ai_improvements,
        ai_model_name=ai_model_name,
        ai_provider=ai_provider,
        spelling_mistakes=spelling_mistakes,
        grammar_mistakes=grammar_mistakes,
        next_band_advice=next_band_advice,
        confidence=confidence,
        vocabulary_highlights=vocabulary_highlights,
        strong_spans=strong_spans,
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

    ai_scores = review.get("ai_scores") or {}
    if not isinstance(ai_scores, dict):
        ai_scores = {}
    ai_status = _ai_status_from_scores(ai_scores)
    ai_band = _ai_band_from_scores(ai_scores)
    ai_available = ai_evaluation_available()

    if review_status == "completed" and band_val is not None:
        message = f"Your Writing band is {band_val:.1f}."
    elif ai_status == AI_STATUS_PENDING:
        message = (
            "Analyzing your essay… AI feedback will appear shortly. "
            "A certified examiner will confirm your band within 24 hours."
        )
    elif ai_status in (AI_STATUS_COMPLETE, AI_STATUS_STUB):
        preview = f" (AI estimate {ai_band:.1f})" if ai_band is not None else ""
        message = (
            f"AI feedback is ready{preview}. A certified examiner is still reviewing "
            "your essay — you will receive your official band within 24 hours."
        )
    elif ai_status == AI_STATUS_FAILED:
        message = (
            "AI analysis is unavailable right now. A certified examiner will review "
            "your essay manually and confirm your band within 24 hours."
        )
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
        ai_status=ai_status,
        ai_band=ai_band,
        ai_available=ai_available,
        submitted_at=submitted_at,
        message=message,
        session_tasks=_session_tasks(attempt, user_id=user_id),
    )
