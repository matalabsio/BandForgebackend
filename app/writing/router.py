"""FastAPI routes for the Writing module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.writing import service
from app.writing.schemas import (
    AutosaveRequest,
    AutosaveResponse,
    StartWritingResponse,
    SubmitWritingRequest,
    SubmitWritingResponse,
    WritingReviewResponse,
)

router = APIRouter(prefix="/api/writing", tags=["writing"])


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
) -> StartWritingResponse:
    return service.start_attempt(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
        part=part,
        force_new=force_new,
        mock_attempt_id=mock_attempt_id,
    )


@router.post("/attempts/{attempt_id}/autosave", response_model=AutosaveResponse)
def autosave_writing(
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


@router.post("/attempts/{attempt_id}/submit", response_model=SubmitWritingResponse)
def submit_writing(
    attempt_id: UUID,
    body: SubmitWritingRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> SubmitWritingResponse:
    payload = [
        {"question_id": str(a.question_id), "user_answer": a.user_answer}
        for a in body.answers
    ]
    return service.submit_attempt(
        attempt_id=attempt_id,
        user_id=current_user.id,
        answers=payload,
    )


@router.get("/attempts/{attempt_id}/review", response_model=WritingReviewResponse)
def writing_review(
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> WritingReviewResponse:
    return service.get_review(attempt_id=attempt_id, user_id=current_user.id)
