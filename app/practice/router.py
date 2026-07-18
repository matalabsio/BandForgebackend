"""Practice hubs API routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.practice import service
from app.practice.schemas import (
    HubCompleteOut,
    MockUnlockOut,
    PracticeHubDetailOut,
    PracticeHubOut,
    PracticeProgressOut,
    SkillName,
)
from app.security.entitlements import require_full_skill_program

router = APIRouter(prefix="/api/practice", tags=["practice"])


@router.get("/hubs", response_model=list[PracticeHubOut])
def list_practice_hubs(
    skill: Annotated[SkillName, Query()],
    user: Annotated[UserPublic, Depends(require_full_skill_program)],
) -> list[PracticeHubOut]:
    return service.list_hubs_with_progress(user_id=UUID(str(user.id)), skill=skill)


@router.get("/hubs/{hub_id}", response_model=PracticeHubDetailOut)
def get_practice_hub(
    hub_id: str,
    user: Annotated[UserPublic, Depends(require_full_skill_program)],
) -> PracticeHubDetailOut:
    return service.get_hub_detail(user_id=UUID(str(user.id)), hub_id=hub_id)


@router.post("/hubs/{hub_id}/complete", response_model=HubCompleteOut)
def complete_practice_hub(
    hub_id: str,
    user: Annotated[UserPublic, Depends(require_full_skill_program)],
) -> HubCompleteOut:
    return service.complete_hub(user_id=UUID(str(user.id)), hub_id=hub_id)


@router.get("/progress", response_model=PracticeProgressOut)
def get_practice_progress(
    user: Annotated[UserPublic, Depends(require_full_skill_program)],
) -> PracticeProgressOut:
    return service.all_skill_progress(UUID(str(user.id)))


@router.get("/mock-unlock", response_model=MockUnlockOut)
def get_mock_unlock(
    skill: Annotated[SkillName, Query()],
    user: Annotated[UserPublic, Depends(require_full_skill_program)],
) -> MockUnlockOut:
    return service.mock_unlock_status(user_id=UUID(str(user.id)), skill=skill)
