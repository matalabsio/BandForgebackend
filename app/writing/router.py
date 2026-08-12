"""FastAPI routes for the Writing module."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.diagnostic.access import assert_mock_access
from app.security.entitlements import assert_premium_mock_access
from app.security.rate_limit import enforce_writing_submit_rate_limit
from app.skill_program_gate import assert_skill_program_module_start
from app.writing import service
from app.writing.schemas import (
    AutosaveRequest,
    AutosaveResponse,
    StartWritingResponse,
    SubmitWritingRequest,
    SubmitWritingResponse,
    WritingPendingResponse,
    WritingReviewResponse,
)
from app.writing.timing import (
    WritingAutosaveTiming,
    WritingStartTiming,
    WritingSubmitTiming,
)

router = APIRouter(prefix="/api/writing", tags=["writing"])


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


@router.post("/{mock_test_id}/start", response_model=StartWritingResponse)
def start_writing(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    part: Annotated[int, Query(ge=1, le=2, description="Writing task 1 or 2")] = 1,
    force_new: Annotated[bool, Query(description="Abandon in-progress and start fresh.")] = False,
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
) -> StartWritingResponse:
    assert_mock_access(user=current_user, mock_test_id=mock_test_id)
    assert_premium_mock_access(user=current_user, mock_test_id=mock_test_id)
    assert_skill_program_module_start(
        user_id=current_user.id,
        skill_context=skill_context,
        from_plan=from_plan,
    )
    started = perf_counter()
    timing = WritingStartTiming()
    try:
        response = service.start_attempt(
            mock_test_id=mock_test_id,
            user_id=current_user.id,
            part=part,
            force_new=force_new,
            mock_attempt_id=mock_attempt_id,
            timing=timing,
        )
        _timing_log(
            "/api/writing/{mock_test_id}/start",
            started,
            200,
            extra=timing.to_log_fields(),
        )
        return response
    except Exception:
        _timing_log(
            "/api/writing/{mock_test_id}/start",
            started,
            500,
            extra=timing.to_log_fields(),
        )
        raise


@router.post("/attempts/{attempt_id}/autosave", response_model=AutosaveResponse)
def autosave_writing(
    attempt_id: UUID,
    body: AutosaveRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> AutosaveResponse:
    started = perf_counter()
    timing = WritingAutosaveTiming()
    try:
        response = service.autosave_answer(
            attempt_id=attempt_id,
            user_id=current_user.id,
            question_id=body.question_id,
            user_answer=body.user_answer,
            timing=timing,
        )
        _timing_log(
            "/api/writing/attempts/{attempt_id}/autosave",
            started,
            200,
            extra=timing.to_log_fields(),
        )
        return response
    except Exception:
        _timing_log(
            "/api/writing/attempts/{attempt_id}/autosave",
            started,
            500,
            extra=timing.to_log_fields(),
        )
        raise


@router.post("/attempts/{attempt_id}/submit", response_model=SubmitWritingResponse)
def submit_writing(
    attempt_id: UUID,
    body: SubmitWritingRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> SubmitWritingResponse:
    started = perf_counter()
    timing = WritingSubmitTiming()
    enforce_writing_submit_rate_limit(user_id=str(current_user.id))
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
            background_tasks=background_tasks,
            on_expiry=body.on_expiry,
        )
        _timing_log(
            "/api/writing/attempts/{attempt_id}/submit",
            started,
            200,
            extra=timing.to_log_fields(),
        )
        return response
    except Exception:
        _timing_log(
            "/api/writing/attempts/{attempt_id}/submit",
            started,
            500,
            extra=timing.to_log_fields(),
        )
        raise


@router.get("/attempts/{attempt_id}/review", response_model=WritingReviewResponse)
def writing_review(
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> WritingReviewResponse:
    return service.get_review(attempt_id=attempt_id, user_id=current_user.id)


@router.get("/attempts/{attempt_id}/pending", response_model=WritingPendingResponse)
def writing_pending(
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> WritingPendingResponse:
    return service.get_pending_status(attempt_id=attempt_id, user_id=current_user.id)
