"""FastAPI routes for the Listening module.

Thin: validates input, calls the service layer, returns typed responses.
All routes require an authenticated user (JWT cookie or Bearer).

TODO: add per-user rate limiting on `start` and `submit`.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.listening import service
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


@router.post(
    "/{mock_test_id}/start",
    response_model=StartListeningResponse,
)
def start_listening(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> StartListeningResponse:
    """Create a new listening attempt for the current user."""
    return service.start_attempt(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
    )


@router.get(
    "/{mock_test_id}/questions",
    response_model=ListeningQuestionsResponse,
)
def get_listening_questions(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> ListeningQuestionsResponse:
    """Return listening questions + signed R2 audio URLs. Never returns correct_answer."""
    return service.get_session_questions(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
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
    payload = [
        {"question_id": str(a.question_id), "user_answer": a.user_answer}
        for a in body.answers
    ]
    return service.submit_attempt(
        attempt_id=attempt_id,
        user_id=current_user.id,
        answers=payload,
    )


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
