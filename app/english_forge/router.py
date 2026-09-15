"""English Forge API — /api/english-forge."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile

from . import service
from .schemas import (
    ConfirmResponseRequest,
    CreateResponseSessionRequest,
    CreateSessionRequest,
    EvaluateRequest,
    EvaluateResponse,
    FeedbackPublic,
    GradeBand,
    PendingStatus,
    ResponsePublic,
    ResponseSessionPublic,
    SessionPublic,
    SpeakPrompt,
)

router = APIRouter(prefix="/api/english-forge", tags=["english-forge"])


@router.get("/prompts", response_model=list[SpeakPrompt])
def get_prompts(grade_band: GradeBand = Query("6-8")) -> list[SpeakPrompt]:
    return service.list_prompts_for_band(grade_band)


@router.get("/prompts/{prompt_id}", response_model=SpeakPrompt)
def get_prompt(prompt_id: str) -> SpeakPrompt:
    return service.get_prompt_or_404(prompt_id)


@router.post("/sessions", response_model=SessionPublic)
def post_session(body: CreateSessionRequest) -> SessionPublic:
    return service.create_session(body)


@router.post(
    "/sessions/{session_id}/response-sessions",
    response_model=ResponseSessionPublic,
)
def post_response_session(
    session_id: UUID,
    body: CreateResponseSessionRequest,
) -> ResponseSessionPublic:
    return service.create_response_session(session_id, body)


@router.post(
    "/sessions/{session_id}/responses/{response_id}/upload",
    response_model=ResponsePublic,
)
async def post_upload_audio(
    session_id: UUID,
    response_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    idempotency_key: str = Form(...),
    duration_sec: int = Form(...),
) -> ResponsePublic:
    """Server-side R2 upload (avoids browser→R2 CORS)."""
    audio_bytes = await file.read()
    return service.upload_response_audio(
        session_id,
        response_id,
        audio_bytes=audio_bytes,
        content_type=file.content_type,
        idempotency_key=idempotency_key,
        duration_sec=duration_sec,
        background_tasks=background_tasks,
    )


@router.post(
    "/sessions/{session_id}/responses/{response_id}/confirm",
    response_model=ResponsePublic,
)
def post_confirm(
    session_id: UUID,
    response_id: UUID,
    body: ConfirmResponseRequest,
    background_tasks: BackgroundTasks,
) -> ResponsePublic:
    return service.confirm_response(
        session_id, response_id, body, background_tasks=background_tasks
    )


@router.post("/sessions/{session_id}/finalize", response_model=PendingStatus)
def post_finalize(
    session_id: UUID,
    background_tasks: BackgroundTasks,
) -> PendingStatus:
    return service.finalize_session(session_id, background_tasks=background_tasks)


@router.get("/sessions/{session_id}/pending", response_model=PendingStatus)
def get_pending(session_id: UUID) -> PendingStatus:
    return service.get_pending(session_id)


@router.get("/sessions/{session_id}/feedback", response_model=FeedbackPublic)
def get_feedback(session_id: UUID) -> FeedbackPublic:
    return service.get_feedback(session_id)


@router.post("/evaluate", response_model=EvaluateResponse)
def post_evaluate(body: EvaluateRequest) -> EvaluateResponse:
    """Direct transcript → coach card (dev / calibration)."""
    return service.evaluate_direct(body)
