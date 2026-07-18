"""FastAPI routes for the Speaking module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.diagnostic.access import assert_mock_access
from app.skill_program_gate import assert_skill_program_module_start
from app.speaking import service
from app.speaking.schemas import (
    SpeakingPendingResponse,
    SpeakingReportResponse,
    StartSpeakingResponse,
    SubmitSpeakingResponse,
)

router = APIRouter(prefix="/api/speaking", tags=["speaking"])


@router.post("/{mock_test_id}/start", response_model=StartSpeakingResponse)
def start_speaking(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    part: Annotated[int, Query(ge=1, le=1, description="Speaking Part 1")] = 1,
    force_new: Annotated[bool, Query(description="Abandon in-progress and start fresh.")] = False,
    mock_attempt_id: Annotated[
        UUID | None,
        Query(description="Parent full-mock attempt for orchestration."),
    ] = None,
    skill_context: Annotated[
        str | None,
        Query(description="Skill-program mock gate (listening|reading|writing|speaking)."),
    ] = None,
) -> StartSpeakingResponse:
    assert_mock_access(user=current_user, mock_test_id=mock_test_id)
    assert_skill_program_module_start(
        user_id=current_user.id,
        skill_context=skill_context,
    )
    return service.start_attempt(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
        part=part,
        force_new=force_new,
        mock_attempt_id=mock_attempt_id,
        student_name=current_user.full_name,
    )


@router.post("/attempts/{attempt_id}/submit", response_model=SubmitSpeakingResponse)
async def submit_speaking(
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    duration_sec: Annotated[int | None, Form()] = None,
) -> SubmitSpeakingResponse:
    content = await file.read()
    return service.submit_attempt(
        attempt_id=attempt_id,
        user_id=current_user.id,
        audio_bytes=content,
        content_type=file.content_type,
        filename=file.filename,
        student_name=current_user.full_name,
        duration_sec=duration_sec,
        background_tasks=background_tasks,
    )


@router.get("/attempts/{attempt_id}/pending", response_model=SpeakingPendingResponse)
def speaking_pending(
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> SpeakingPendingResponse:
    return service.get_pending_status(
        attempt_id=attempt_id,
        user_id=current_user.id,
        student_name=current_user.full_name,
    )


@router.get("/attempts/{attempt_id}/report", response_model=SpeakingReportResponse)
def speaking_report(
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> SpeakingReportResponse:
    return service.get_speaking_report(
        attempt_id=attempt_id,
        user_id=current_user.id,
        student_name=current_user.full_name,
    )
