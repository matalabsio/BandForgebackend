"""FastAPI routes for the Speaking module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.diagnostic.access import assert_mock_access
from app.notifications import preferences
from app.security.entitlements import assert_premium_mock_access
from app.security.rate_limit import enforce_speaking_submit_rate_limit
from app.skill_program_gate import assert_skill_program_module_start
from app.speaking import service
from app.speaking.schemas import (
    ConfirmSpeakingResponseRequest,
    CreateSpeakingResponseSessionRequest,
    FinalizeSpeakingRequest,
    SpeakingEligibilityResponse,
    SpeakingPendingResponse,
    SpeakingReportResponse,
    SpeakingResponsePublic,
    SpeakingResponseSession,
    StartSpeakingResponse,
    SubmitSpeakingResponse,
    NotificationPreferencesResponse,
    PatchNotificationPreferencesRequest,
)

router = APIRouter(prefix="/api/speaking", tags=["speaking"])


@router.get(
    "/notification-preferences", response_model=NotificationPreferencesResponse
)
def notification_preferences(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> NotificationPreferencesResponse:
    return preferences.get_preferences(current_user.id)


@router.patch(
    "/notification-preferences", response_model=NotificationPreferencesResponse
)
def update_notification_preferences(
    body: PatchNotificationPreferencesRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> NotificationPreferencesResponse:
    return preferences.patch_preferences(current_user.id, body)


@router.get("/{mock_test_id}/eligibility", response_model=SpeakingEligibilityResponse)
def speaking_eligibility(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    mock_attempt_id: UUID | None = None,
) -> SpeakingEligibilityResponse:
    assert_mock_access(user=current_user, mock_test_id=mock_test_id)
    return service.get_eligibility(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
        mock_attempt_id=mock_attempt_id,
    )


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
    from_plan: Annotated[
        bool,
        Query(description="Plan-origin start bypasses 12/12 unlock but requires entitlement."),
    ] = False,
) -> StartSpeakingResponse:
    assert_mock_access(user=current_user, mock_test_id=mock_test_id)
    assert_premium_mock_access(user=current_user, mock_test_id=mock_test_id)
    assert_skill_program_module_start(
        user_id=current_user.id,
        skill_context=skill_context,
        from_plan=from_plan,
    )
    response = service.start_attempt(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
        part=part,
        force_new=force_new,
        mock_attempt_id=mock_attempt_id,
        student_name=current_user.full_name,
    )
    from app.practice.writing_skill_mock import maybe_consume_after_new_mock_start

    maybe_consume_after_new_mock_start(
        user_id=current_user.id,
        mock_test_id=mock_test_id,
        created_new=not response.resumed,
    )
    return response


@router.post(
    "/attempts/{attempt_id}/responses",
    response_model=SpeakingResponsePublic,
)
async def upload_speaking_response(
    request: Request,
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
    question_id: Annotated[UUID, Form()],
    part: Annotated[int, Form(ge=1, le=3)],
    sequence_number: Annotated[int, Form(ge=1)],
    duration_sec: Annotated[int, Form(ge=5)],
    file: UploadFile = File(...),
) -> SpeakingResponsePublic:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > service.SPEAKING_MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Recording is too large.",
                )
        except ValueError:
            pass
    content = await file.read()
    if len(content) > service.SPEAKING_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Recording is too large.",
        )
    return service.upload_response(
        attempt_id=attempt_id,
        user_id=current_user.id,
        question_id=question_id,
        part=part,
        sequence_number=sequence_number,
        duration_sec=duration_sec,
        audio_bytes=content,
        content_type=file.content_type,
        filename=file.filename,
        background_tasks=background_tasks,
    )


@router.post(
    "/attempts/{attempt_id}/response-sessions",
    response_model=SpeakingResponseSession,
)
def create_speaking_response_session(
    attempt_id: UUID,
    body: CreateSpeakingResponseSessionRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> SpeakingResponseSession:
    return service.create_response_session(
        attempt_id=attempt_id,
        user_id=current_user.id,
        request=body,
    )


@router.post(
    "/attempts/{attempt_id}/responses/{response_id}/confirm",
    response_model=SpeakingResponsePublic,
)
def confirm_speaking_response(
    attempt_id: UUID,
    response_id: UUID,
    body: ConfirmSpeakingResponseRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> SpeakingResponsePublic:
    return service.confirm_response(
        attempt_id=attempt_id,
        response_id=response_id,
        user_id=current_user.id,
        request=body,
        background_tasks=background_tasks,
    )


@router.get(
    "/attempts/{attempt_id}/responses",
    response_model=list[SpeakingResponsePublic],
)
def list_speaking_responses(
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> list[SpeakingResponsePublic]:
    return service.list_responses(attempt_id=attempt_id, user_id=current_user.id)


@router.post(
    "/attempts/{attempt_id}/finalize",
    response_model=SubmitSpeakingResponse,
)
def finalize_speaking(
    attempt_id: UUID,
    body: FinalizeSpeakingRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> SubmitSpeakingResponse:
    enforce_speaking_submit_rate_limit(user_id=str(current_user.id))
    return service.finalize_attempt(
        attempt_id=attempt_id,
        user_id=current_user.id,
        manifest_hash=body.manifest_hash,
        student_name=current_user.full_name,
        background_tasks=background_tasks,
    )


@router.post("/attempts/{attempt_id}/submit", response_model=SubmitSpeakingResponse)
async def submit_speaking(
    request: Request,
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    duration_sec: Annotated[int | None, Form()] = None,
) -> SubmitSpeakingResponse:
    enforce_speaking_submit_rate_limit(user_id=str(current_user.id))
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > service.SPEAKING_MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Recording is too large.",
                )
        except ValueError:
            pass
    content = await file.read()
    if len(content) > service.SPEAKING_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Recording is too large.",
        )
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
    background_tasks: BackgroundTasks,
) -> SpeakingPendingResponse:
    return service.get_pending_status(
        attempt_id=attempt_id,
        user_id=current_user.id,
        student_name=current_user.full_name,
        background_tasks=background_tasks,
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
