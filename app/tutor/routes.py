"""AI Learning Assistant API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.tutor.schemas import TutorChatRequest, TutorChatResponse, TutorSuggestionsResponse
from app.tutor import service as tutor_service

router = APIRouter(prefix="/api/tutor", tags=["tutor"])


@router.post("/chat", response_model=TutorChatResponse)
async def tutor_chat(
    body: TutorChatRequest,
    user: Annotated[UserPublic, Depends(get_current_user)],
) -> TutorChatResponse:
    """Contextual writing tutor — essay + evaluation + history injected server-side."""
    return await tutor_service.chat(UUID(str(user.id)), body)


@router.get("/suggestions", response_model=TutorSuggestionsResponse)
def tutor_suggestions(
    user: Annotated[UserPublic, Depends(get_current_user)],
    attempt_id: UUID | None = Query(default=None),
) -> TutorSuggestionsResponse:
    return tutor_service.suggestions_for_user(UUID(str(user.id)), attempt_id)
