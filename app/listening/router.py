"""FastAPI routes for the Listening module.

Thin: validates input, calls the service layer, returns typed responses.
All routes require an authenticated user (JWT cookie or Bearer).

TODO: add per-user rate limiting on `start` and `submit`.
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.diagnostic.access import assert_mock_access
from app.security.entitlements import assert_premium_mock_access
from app.skill_program_gate import assert_skill_program_module_start
from app.listening import service
from app.listening.timing import ListeningStartTiming, ListeningSubmitTiming
from app.listening.schemas import (
    AutosaveRequest,
    AutosaveResponse,
    ListeningQuestionsResponse,
    ListeningScoreReport,
    StartListeningResponse,
    SubmitListeningRequest,
    SubmitListeningResponse,
)

router = APIRouter(prefix="/api/listening", tags=["listening"])


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


@router.post(
    "/{mock_test_id}/start",
    response_model=StartListeningResponse,
)
def start_listening(
    mock_test_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    force_new: Annotated[
        bool,
        Query(
            description="Abandon the current in-progress attempt and start a fresh one.",
        ),
    ] = False,
    part: Annotated[int, Query(ge=1, le=4, description="Listening part 1–4")] = 1,
    mock_attempt_id: Annotated[
        UUID | None,
        Query(description="Parent full-mock attempt for orchestration."),
    ] = None,
    include_questions: Annotated[
        bool,
        Query(description="Include questions and presigned audio in the start response."),
    ] = True,
    skill_context: Annotated[
        str | None,
        Query(description="Skill-program mock gate (listening|reading|writing|speaking)."),
    ] = None,
    from_plan: Annotated[
        bool,
        Query(description="Personalized study-plan practice (skip 12/12 mock unlock)."),
    ] = False,
) -> StartListeningResponse:
    """Start or resume a listening attempt for the current user."""
    assert_mock_access(user=current_user, mock_test_id=mock_test_id)
    assert_premium_mock_access(user=current_user, mock_test_id=mock_test_id)
    assert_skill_program_module_start(
        user_id=current_user.id,
        skill_context=skill_context,
        from_plan=from_plan,
    )
    started = perf_counter()
    timing = ListeningStartTiming()
    try:
        response = service.start_attempt(
            mock_test_id=mock_test_id,
            user_id=current_user.id,
            force_new=force_new,
            part=part,
            mock_attempt_id=mock_attempt_id,
            include_questions=include_questions,
            timing=timing,
        )
        from app.practice.writing_skill_mock import maybe_consume_after_new_mock_start

        maybe_consume_after_new_mock_start(
            user_id=current_user.id,
            mock_test_id=mock_test_id,
            created_new=not response.resumed,
        )
        if mock_attempt_id is not None:
            background_tasks.add_task(
                service.schedule_stale_listening_cleanup,
                user_id=current_user.id,
                mock_test_id=mock_test_id,
                mock_attempt_id=mock_attempt_id,
                part=part,
            )
        _timing_log(
            "/api/listening/{mock_test_id}/start",
            started,
            200,
            extra=timing.to_log_fields(),
        )
        return response
    except Exception:
        _timing_log(
            "/api/listening/{mock_test_id}/start",
            started,
            500,
            extra=timing.to_log_fields(),
        )
        raise


@router.get(
    "/{mock_test_id}/questions",
    response_model=ListeningQuestionsResponse,
)
def get_listening_questions(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    part: Annotated[
        int | None,
        Query(ge=1, le=4, description="Return only this part (M01 multi-part mock)."),
    ] = None,
) -> ListeningQuestionsResponse:
    """Return listening questions + signed R2 audio URLs. Never returns correct_answer."""
    started = perf_counter()
    try:
        response = service.get_session_questions(
            mock_test_id=mock_test_id,
            user_id=current_user.id,
            part=part,
        )
        _timing_log("/api/listening/{mock_test_id}/questions", started, 200)
        return response
    except Exception:
        _timing_log("/api/listening/{mock_test_id}/questions", started, 500)
        raise


@router.get("/{mock_test_id}/part-audio")
def stream_part_audio_route(
    mock_test_id: UUID,
    request: Request,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    attempt_id: Annotated[UUID, Query(description="In-progress listening attempt id.")],
    part: Annotated[int, Query(ge=1, le=4, description="Listening part 1–4")] = 1,
):
    """Stream part audio through the API (same-origin for browser playback)."""
    body, headers, status_code = service.stream_part_audio(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
        attempt_id=attempt_id,
        part=part,
        range_header=request.headers.get("range"),
    )
    return StreamingResponse(
        body,
        status_code=status_code,
        media_type=headers.get("Content-Type", "audio/mpeg"),
        headers=headers,
    )


@router.post(
    "/attempts/{attempt_id}/autosave",
    response_model=AutosaveResponse,
)
def autosave_listening_answer(
    attempt_id: UUID,
    body: AutosaveRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> AutosaveResponse:
    """Upsert a single answer for an in-progress attempt (idempotent)."""
    return service.autosave_answer(
        attempt_id=attempt_id,
        user_id=current_user.id,
        question_id=body.question_id,
        user_answer=body.user_answer,
    )


@router.post(
    "/attempts/{attempt_id}/submit",
    response_model=SubmitListeningResponse,
)
def submit_listening_attempt(
    attempt_id: UUID,
    body: SubmitListeningRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> SubmitListeningResponse:
    """Score the attempt, write module_scores, and return band + skill breakdown."""
    started = perf_counter()
    timing = ListeningSubmitTiming()
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
            "/api/listening/attempts/{attempt_id}/submit",
            started,
            200,
            extra=timing.to_log_fields(),
        )
        return response
    except Exception:
        _timing_log(
            "/api/listening/attempts/{attempt_id}/submit",
            started,
            500,
            extra=timing.to_log_fields(),
        )
        raise


@router.get(
    "/attempts/{attempt_id}/score-report",
    response_model=ListeningScoreReport,
)
def listening_score_report(
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> ListeningScoreReport:
    """Return the persisted band + skill breakdown for a completed attempt."""
    return service.get_score_report(
        attempt_id=attempt_id,
        user_id=current_user.id,
    )
