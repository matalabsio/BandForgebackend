"""Practice hubs API routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.auth.schemas import UserPublic
from app.practice import service
from app.practice.access import require_practice_access
from app.practice.schemas import (
    ExerciseStartOut,
    ExerciseSubmitOut,
    ExerciseSubmitRequest,
    HubCompleteOut,
    MockUnlockOut,
    PracticeHubDetailOut,
    PracticeHubOut,
    PracticeProgressOut,
    PracticeWritingReviewOut,
    SkillName,
    WritingSkillExamModuleOut,
    WritingSkillExamModuleRequest,
)
from app.practice.writing_skill_track import set_writing_skill_exam_module

router = APIRouter(prefix="/api/practice", tags=["practice"])


@router.get("/hubs", response_model=list[PracticeHubOut])
def list_practice_hubs(
    skill: Annotated[SkillName, Query()],
    user: Annotated[UserPublic, Depends(require_practice_access)],
) -> list[PracticeHubOut]:
    return service.list_hubs_with_progress(user_id=UUID(str(user.id)), skill=skill)


@router.get("/hubs/{hub_id}", response_model=PracticeHubDetailOut)
def get_practice_hub(
    hub_id: str,
    user: Annotated[UserPublic, Depends(require_practice_access)],
) -> PracticeHubDetailOut:
    return service.get_hub_detail(user_id=UUID(str(user.id)), hub_id=hub_id)


@router.get("/hubs/{hub_id}/watch-video")
def stream_hub_watch_video_route(
    hub_id: str,
    request: Request,
    user: Annotated[UserPublic, Depends(require_practice_access)],
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
    user: Annotated[UserPublic, Depends(require_practice_access)],
) -> HubCompleteOut:
    return service.complete_hub(user_id=UUID(str(user.id)), hub_id=hub_id)


@router.post("/hubs/{hub_id}/exercise/start", response_model=ExerciseStartOut)
def start_practice_exercise(
    hub_id: str,
    user: Annotated[UserPublic, Depends(require_practice_access)],
    part: int | None = Query(default=None, ge=1, le=4),
) -> ExerciseStartOut:
    return service.start_hub_exercise(
        user_id=UUID(str(user.id)), hub_id=hub_id, part=part
    )


@router.get("/hubs/{hub_id}/exercise/{attempt_id}/part-audio")
def stream_practice_exercise_audio(
    hub_id: str,
    attempt_id: str,
    request: Request,
    user: Annotated[UserPublic, Depends(require_practice_access)],
):
    """Private bank listening MP3 — auth + in-progress attempt; Range supported."""
    body, headers, status_code = service.stream_hub_exercise_audio(
        user_id=UUID(str(user.id)),
        hub_id=hub_id,
        attempt_id=attempt_id,
        range_header=request.headers.get("range"),
    )
    return StreamingResponse(
        body,
        status_code=status_code,
        media_type=headers.get("Content-Type", "audio/mpeg"),
        headers=headers,
    )


@router.post(
    "/hubs/{hub_id}/exercise/{attempt_id}/submit",
    response_model=ExerciseSubmitOut,
)
def submit_practice_exercise(
    hub_id: str,
    attempt_id: str,
    body: ExerciseSubmitRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[UserPublic, Depends(require_practice_access)],
) -> ExerciseSubmitOut:
    return service.submit_hub_exercise(
        user_id=UUID(str(user.id)),
        hub_id=hub_id,
        attempt_id=attempt_id,
        answers=body.answers,
        background_tasks=background_tasks,
    )


@router.get(
    "/hubs/{hub_id}/exercise/{attempt_id}/writing-review",
    response_model=PracticeWritingReviewOut,
)
def practice_writing_review(
    hub_id: str,
    attempt_id: str,
    user: Annotated[UserPublic, Depends(require_practice_access)],
) -> PracticeWritingReviewOut:
    """Poll AI writing feedback for a bank practice essay (same engine as mocks)."""
    from app.practice.writing_ai import get_practice_writing_review

    data = get_practice_writing_review(
        user_id=UUID(str(user.id)),
        hub_id=hub_id,
        attempt_id=attempt_id,
    )
    return PracticeWritingReviewOut.model_validate(data)


@router.get("/progress", response_model=PracticeProgressOut)
def get_practice_progress(
    user: Annotated[UserPublic, Depends(require_practice_access)],
) -> PracticeProgressOut:
    return service.all_skill_progress(UUID(str(user.id)))


@router.post(
    "/writing-skill/exam-module",
    response_model=WritingSkillExamModuleOut,
)
def set_writing_skill_track(
    body: WritingSkillExamModuleRequest,
    user: Annotated[UserPublic, Depends(require_practice_access)],
) -> WritingSkillExamModuleOut:
    """Select/lock Writing Skill Academic vs GT track on user_program_usage."""
    out = set_writing_skill_exam_module(
        user_id=UUID(str(user.id)), exam_module=body.exam_module
    )
    return WritingSkillExamModuleOut(
        exam_module=out["exam_module"],  # type: ignore[arg-type]
        usage_id=str(out["usage_id"]),
        changed=bool(out.get("changed")),
    )


@router.get("/mock-unlock", response_model=MockUnlockOut)
def get_mock_unlock(
    skill: Annotated[SkillName, Query()],
    user: Annotated[UserPublic, Depends(require_practice_access)],
) -> MockUnlockOut:
    """FSP: 12/12 skill mock. Writing Skill: course-complete + one-shot quota."""
    return service.mock_unlock_status(user_id=UUID(str(user.id)), skill=skill)
