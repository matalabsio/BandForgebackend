"""Practice hubs API routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.practice import service
from app.practice.schemas import (
    ExerciseStartOut,
    ExerciseSubmitOut,
    ExerciseSubmitRequest,
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


@router.get("/hubs/{hub_id}/watch-video")
def stream_hub_watch_video_route(
    hub_id: str,
    request: Request,
    user: Annotated[UserPublic, Depends(require_full_skill_program)],
):
    """Private set Watch video — auth + hub access; not a public shareable URL."""
    body, headers, status_code = service.stream_hub_watch_video(
        user_id=UUID(str(user.id)),
        hub_id=hub_id,
        range_header=request.headers.get("range"),
    )
    return StreamingResponse(
        body,
        status_code=status_code,
        media_type=headers.get("Content-Type", "video/mp4"),
        headers=headers,
    )


@router.post("/hubs/{hub_id}/complete", response_model=HubCompleteOut)
def complete_practice_hub(
    hub_id: str,
    user: Annotated[UserPublic, Depends(require_full_skill_program)],
) -> HubCompleteOut:
    return service.complete_hub(user_id=UUID(str(user.id)), hub_id=hub_id)


@router.post("/hubs/{hub_id}/exercise/start", response_model=ExerciseStartOut)
def start_practice_exercise(
    hub_id: str,
    user: Annotated[UserPublic, Depends(require_full_skill_program)],
    part: int | None = Query(default=None, ge=1, le=4),
) -> ExerciseStartOut:
    return service.start_hub_exercise(
        user_id=UUID(str(user.id)), hub_id=hub_id, part=part
    )


@router.post(
    "/hubs/{hub_id}/exercise/{attempt_id}/submit",
    response_model=ExerciseSubmitOut,
)
def submit_practice_exercise(
    hub_id: str,
    attempt_id: str,
    body: ExerciseSubmitRequest,
    user: Annotated[UserPublic, Depends(require_full_skill_program)],
) -> ExerciseSubmitOut:
    return service.submit_hub_exercise(
        user_id=UUID(str(user.id)),
        hub_id=hub_id,
        attempt_id=attempt_id,
        answers=body.answers,
    )


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
