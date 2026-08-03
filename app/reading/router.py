"""FastAPI routes for the Reading module."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response

from app.auth.dependencies import get_current_user, get_current_user_timed
from app.auth.schemas import UserPublic
from app.diagnostic.access import assert_mock_access
from app.security.entitlements import assert_premium_mock_access
from app.skill_program_gate import assert_skill_program_module_start
from app.perf.timing import (
    PerfTimer,
    is_perf_enabled,
    new_request_id,
    perf_summary,
    reset_perf_context,
    set_request_id,
)
from app.reading import service
from app.reading.timing import (
    ReadingAutosaveTiming,
    ReadingStartTiming,
    ReadingSubmitTiming,
)
from app.reading.schemas import (
    AutosaveRequest,
    AutosaveResponse,
    ReadingQuestionsResponse,
    ReadingScoreReport,
    StartReadingResponse,
    SubmitReadingRequest,
    SubmitReadingResponse,
)

router = APIRouter(prefix="/api/reading", tags=["reading"])


def _timing_log(
    route: str,
    started: float,
    status_code: int,
    *,
    extra: dict | None = None,
) -> None:
    payload: dict = {
        "route": route,
        "duration_ms": round((perf_counter() - started) * 1000, 2),
        "status": status_code,
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload))


def _resolve_request_id(request: Request) -> str:
    header_id = request.headers.get("X-Request-Id")
    if header_id and header_id.strip():
        return header_id.strip()
    return new_request_id()


@router.post("/{mock_test_id}/start", response_model=StartReadingResponse)
def start_reading(
    mock_test_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    force_new: Annotated[
        bool,
        Query(description="Abandon in-progress attempt and start fresh."),
    ] = False,
    include_questions: Annotated[
        bool,
        Query(
            description="Return passage and questions in the same response (faster exam load).",
        ),
    ] = True,
    part: Annotated[
        int,
        Query(ge=1, le=4, alias="passage", description="Reading passage 1–4 (stored as part)."),
    ] = 1,
    mock_attempt_id: Annotated[
        UUID | None,
        Query(description="Parent full-mock attempt for orchestration."),
    ] = None,
    skill_context: Annotated[
        str | None,
        Query(description="Skill-program mock gate (listening|reading|writing|speaking)."),
    ] = None,
    from_plan: Annotated[
        bool,
        Query(description="Personalized study-plan practice (skip 12/12 mock unlock)."),
    ] = False,
) -> StartReadingResponse:
    assert_mock_access(user=current_user, mock_test_id=mock_test_id)
    assert_premium_mock_access(user=current_user, mock_test_id=mock_test_id)
    assert_skill_program_module_start(
        user_id=current_user.id,
        skill_context=skill_context,
        from_plan=from_plan,
    )
    started = perf_counter()
    timing = ReadingStartTiming()
    try:
        response = service.start_attempt(
            mock_test_id=mock_test_id,
            user_id=current_user.id,
            force_new=force_new,
            include_questions=include_questions,
            part=part,
            mock_attempt_id=mock_attempt_id,
            timing=timing,
        )
        if mock_attempt_id is not None:
            background_tasks.add_task(
                service.schedule_stale_reading_cleanup,
                user_id=current_user.id,
                mock_test_id=mock_test_id,
                mock_attempt_id=mock_attempt_id,
                part=part,
            )
        _timing_log(
            "/api/reading/{mock_test_id}/start",
            started,
            200,
            extra=timing.to_log_fields(),
        )
        return response
    except Exception:
        _timing_log(
            "/api/reading/{mock_test_id}/start",
            started,
            500,
            extra=timing.to_log_fields(),
        )
        raise


@router.get("/{mock_test_id}/questions", response_model=ReadingQuestionsResponse)
def get_reading_questions(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    part: Annotated[
        int | None,
        Query(ge=1, le=4, alias="passage", description="Passage filter for M01."),
    ] = None,
) -> ReadingQuestionsResponse:
    started = perf_counter()
    try:
        response = service.get_session_questions(
            mock_test_id=mock_test_id,
            user_id=current_user.id,
            part=part,
        )
        _timing_log("/api/reading/{mock_test_id}/questions", started, 200)
        return response
    except Exception:
        _timing_log("/api/reading/{mock_test_id}/questions", started, 500)
        raise


@router.post("/attempts/{attempt_id}/autosave", response_model=AutosaveResponse)
def autosave_reading_answer(
    attempt_id: UUID,
    body: AutosaveRequest,
    request: Request,
    response: Response,
    current_user: Annotated[UserPublic, Depends(get_current_user_timed)],
) -> AutosaveResponse:
    started = perf_counter()
    request_id = _resolve_request_id(request)
    reset_perf_context(request_id)
    set_request_id(request_id)
    response.headers["X-Request-Id"] = request_id

    auth_ms = int(getattr(request.state, "auth_ms", 0) or 0)
    timing = ReadingAutosaveTiming()
    perf_timer = PerfTimer("reading-autosave") if is_perf_enabled() else None

    try:
        result = service.autosave_answer(
            attempt_id=attempt_id,
            user_id=current_user.id,
            question_id=body.question_id,
            user_answer=body.user_answer,
            timing=timing,
            auth_ms=auth_ms,
            request_id=request_id,
        )
        timing.duration_ms = round((perf_counter() - started) * 1000)

        if perf_timer is not None:
            if auth_ms:
                print(f"[reading-autosave] auth: {auth_ms}ms")
            if timing.attempt_fetch_ms:
                print(
                    f"[reading-autosave] attempt-fetch: {timing.attempt_fetch_ms}ms"
                )
            if timing.question_validate_ms:
                print(
                    "[reading-autosave] question-validate: "
                    f"{timing.question_validate_ms}ms"
                )
            if timing.answer_upsert_ms:
                print(
                    f"[reading-autosave] answer-upsert: {timing.answer_upsert_ms}ms"
                )
            print(f"[reading-autosave] TOTAL: {timing.duration_ms}ms")

        perf_summary(
            "/api/reading/autosave",
            request_id,
            auth_ms=auth_ms,
            attempt_fetch_ms=timing.attempt_fetch_ms,
            question_validate_ms=timing.question_validate_ms,
            answer_upsert_ms=timing.answer_upsert_ms,
            db_ms=(
                timing.attempt_fetch_ms
                + timing.question_validate_ms
                + timing.answer_upsert_ms
            ),
            db_query_count=timing.db_query_count,
            cache_ms=0,
            serialize_ms=0,
            total_ms=timing.duration_ms,
        )

        _timing_log(
            f"/api/reading/attempts/{attempt_id}/autosave",
            started,
            200,
            extra=timing.to_log_fields(),
        )
        return result
    except Exception:
        timing.duration_ms = round((perf_counter() - started) * 1000)
        _timing_log(
            f"/api/reading/attempts/{attempt_id}/autosave",
            started,
            500,
            extra=timing.to_log_fields(),
        )
        raise


@router.post("/attempts/{attempt_id}/submit", response_model=SubmitReadingResponse)
def submit_reading_attempt(
    attempt_id: UUID,
    body: SubmitReadingRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> SubmitReadingResponse:
    started = perf_counter()
    timing = ReadingSubmitTiming()
    payload = [
        {"question_id": str(a.question_id), "user_answer": a.user_answer}
        for a in body.answers
    ]
    try:
        response = service.submit_attempt(
            attempt_id=attempt_id,
            user_id=current_user.id,
            answers=payload,
            timing=timing,
        )
        _timing_log(
            "/api/reading/attempts/{attempt_id}/submit",
            started,
            200,
            extra=timing.to_log_fields(),
        )
        return response
    except Exception:
        _timing_log(
            "/api/reading/attempts/{attempt_id}/submit",
            started,
            500,
            extra=timing.to_log_fields(),
        )
        raise


@router.get("/attempts/{attempt_id}/score-report", response_model=ReadingScoreReport)
def reading_score_report(
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> ReadingScoreReport:
    return service.get_score_report(attempt_id=attempt_id, user_id=current_user.id)
