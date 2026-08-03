"""Student learning profile API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.learning.schemas import (
    GeneratePlanRequest,
    LearningProfileResponse,
    TaskStatusResponse,
    TaskStatusUpdate,
)
from app.learning.service import ensure_profile, generate_personalized_plan, update_task_status
from app.security.entitlements import require_full_skill_program

router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.get("/profile", response_model=LearningProfileResponse)
def get_learning_profile(
    user: Annotated[UserPublic, Depends(get_current_user)],
) -> LearningProfileResponse:
    """Return adaptive learning profile (creates/refreshes when stale)."""
    return ensure_profile(UUID(str(user.id)))


@router.post("/refresh", response_model=LearningProfileResponse)
def refresh_learning_profile(
    user: Annotated[UserPublic, Depends(get_current_user)],
) -> LearningProfileResponse:
    """Force recompute from latest writing/speaking/L-R/diagnostic signals."""
    return ensure_profile(UUID(str(user.id)), force=True)


@router.post("/plan/generate", response_model=LearningProfileResponse)
def generate_learning_plan(
    body: GeneratePlanRequest,
    user: Annotated[UserPublic, Depends(require_full_skill_program)],
) -> LearningProfileResponse:
    """Generate or refresh the exam-date-bound personalized study plan."""
    return generate_personalized_plan(UUID(str(user.id)), plan_tier=body.plan_tier)


@router.patch("/tasks/{task_id}", response_model=TaskStatusResponse)
def patch_learning_task(
    task_id: str,
    body: TaskStatusUpdate,
    user: Annotated[UserPublic, Depends(get_current_user)],
) -> TaskStatusResponse:
    study_plan = update_task_status(UUID(str(user.id)), task_id, body.status)
    return TaskStatusResponse(
        task_id=task_id,
        status=body.status,
        study_plan=study_plan,
    )
