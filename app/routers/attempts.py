from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.schemas.test_engine import SubmitAnswersRequest, SubmitAnswersResponse
from app.services import test_engine

router = APIRouter(prefix="/api/attempts", tags=["attempts"])


@router.post("/{attempt_id}/submit", response_model=SubmitAnswersResponse)
def submit_attempt(
    attempt_id: UUID,
    body: SubmitAnswersRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> SubmitAnswersResponse:
    """Submit answers for an in-progress attempt. Does not score (Day 3)."""
    answers = [
        {
            "question_id": str(item.question_id),
            "user_answer": item.user_answer,
        }
        for item in body.answers
    ]
    return test_engine.submit_answers(
        attempt_id,
        user_id=current_user.id,
        answers=answers,
    )
