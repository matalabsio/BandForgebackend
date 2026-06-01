"""FastAPI routes for the Reading module."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.reading import service
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


def _timing_log(route: str, started: float, status_code: int) -> None:
    print(
        json.dumps(
            {
                "route": route,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
                "cache_hit": False,
                "cache_layer": "none",
                "status": status_code,
            }
        )
    )


@router.post("/{mock_test_id}/start", response_model=StartReadingResponse)
def start_reading(
    mock_test_id: UUID,
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
) -> StartReadingResponse:
    started = perf_counter()
    try:
        response = service.start_attempt(
            mock_test_id=mock_test_id,
            user_id=current_user.id,
            force_new=force_new,
            include_questions=include_questions,
            part=part,
            mock_attempt_id=mock_attempt_id,
        )
        _timing_log("/api/reading/{mock_test_id}/start", started, 200)
        return response
    except Exception:
        _timing_log("/api/reading/{mock_test_id}/start", started, 500)
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
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> AutosaveResponse:
    return service.autosave_answer(
        attempt_id=attempt_id,
        user_id=current_user.id,
        question_id=body.question_id,
        user_answer=body.user_answer,
    )


@router.post("/attempts/{attempt_id}/submit", response_model=SubmitReadingResponse)
def submit_reading_attempt(
    attempt_id: UUID,
    body: SubmitReadingRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> SubmitReadingResponse:
    payload = [
        {"question_id": str(a.question_id), "user_answer": a.user_answer}
        for a in body.answers
    ]
    return service.submit_attempt(
        attempt_id=attempt_id,
        user_id=current_user.id,
        answers=payload,
    )


@router.get("/attempts/{attempt_id}/score-report", response_model=ReadingScoreReport)
def reading_score_report(
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> ReadingScoreReport:
    return service.get_score_report(attempt_id=attempt_id, user_id=current_user.id)
