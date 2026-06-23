"""Admin API routes — all require admin role."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.admin import audit_routes, dashboard, mocks, mocks_ingest, questions, speaking, users
from app.admin.dependencies import require_admin, require_super_admin
from app.admin.schemas import (
    AdminMockDetail,
    AdminMockListItem,
    CreateMockRequest,
    PatchMockRequest,
    AdminQuestionDetail,
    AdminUserDetail,
    AdminUserListResponse,
    AdminUserOverview,
    ApproveSpeakingRequest,
    PatchSpeakingReviewRequest,
    AuditLogResponse,
    DashboardMetrics,
    DashboardOverview,
    IngestPublishRequest,
    IngestPublishResponse,
    IngestValidateRequest,
    IngestValidateResponse,
    PatchAdminUserRequest,
    PatchMockStatusRequest,
    PatchQuestionRequest,
    QuestionTreeResponse,
    SpeakingQueueResponse,
    SpeakingReviewDetail,
)
from app.auth.schemas import UserPublic
from app.listening.service import invalidate_listening_audio_caches
from app.storage.r2 import object_exists, object_head, upload_object

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard/metrics", response_model=DashboardMetrics)
def get_metrics(
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> DashboardMetrics:
    return dashboard.get_dashboard_metrics()


@router.get("/dashboard/overview", response_model=DashboardOverview)
def get_dashboard_overview_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> DashboardOverview:
    return dashboard.get_dashboard_overview()


@router.get("/users", response_model=AdminUserListResponse)
def list_users_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
    q: str | None = None,
    role: str | None = None,
    active: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> AdminUserListResponse:
    return users.list_users(q=q, role=role, active=active, page=page, page_size=page_size)


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def get_user_route(
    user_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> AdminUserDetail:
    return users.get_user_detail(user_id)


@router.get("/users/{user_id}/overview", response_model=AdminUserOverview)
def get_user_overview_route(
    user_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> AdminUserOverview:
    return users.get_user_overview(user_id)


@router.get("/users/{user_id}/attempts")
def list_user_attempts_route(
    user_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
):
    return users.list_user_attempts(user_id)


@router.patch("/users/{user_id}", response_model=AdminUserDetail)
def patch_user_route(
    user_id: UUID,
    body: PatchAdminUserRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
) -> AdminUserDetail:
    return users.patch_user(
        user_id=user_id,
        body=body,
        admin_id=admin.id,
        is_super_admin=admin.role == "super_admin",
    )


@router.get("/mocks", response_model=list[AdminMockListItem])
def list_mocks_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> list[AdminMockListItem]:
    return mocks.list_mocks()


@router.post("/mocks", response_model=AdminMockDetail, status_code=201)
def create_mock_route(
    body: CreateMockRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
) -> AdminMockDetail:
    return mocks.create_mock(body=body, admin_id=admin.id)


@router.get("/mocks/{mock_id}", response_model=AdminMockDetail)
def get_mock_route(
    mock_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> AdminMockDetail:
    return mocks.get_mock_detail(mock_id)


@router.patch("/mocks/{mock_id}", response_model=AdminMockDetail)
def patch_mock_route(
    mock_id: UUID,
    body: PatchMockRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
) -> AdminMockDetail:
    return mocks.patch_mock(mock_id=mock_id, body=body, admin_id=admin.id)


@router.patch("/mocks/{mock_id}/status", response_model=AdminMockDetail)
def patch_mock_status_route(
    mock_id: UUID,
    body: PatchMockStatusRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
) -> AdminMockDetail:
    return mocks.patch_mock_status(mock_id=mock_id, body=body, admin_id=admin.id)


@router.post("/mocks/{mock_id}/ingest/validate", response_model=IngestValidateResponse)
def validate_ingest_route(
    mock_id: UUID,
    body: IngestValidateRequest,
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> IngestValidateResponse:
    return mocks_ingest.validate_ingest(body, mock_id)


@router.post("/mocks/{mock_id}/ingest/publish", response_model=IngestPublishResponse)
def publish_ingest_route(
    mock_id: UUID,
    body: IngestPublishRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
) -> IngestPublishResponse:
    return mocks_ingest.publish_ingest(mock_id=mock_id, body=body, admin_id=admin.id)


@router.get("/mocks/{mock_id}/ingest/audio")
def listening_audio_status_route(
    mock_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
    part: int = Query(..., ge=1, le=4),
    key: str | None = None,
):
    audio_key = key or f"listening/{mock_id}/part-{part}/full.mp3"
    meta = object_head(audio_key)
    size_bytes = int(meta["size"]) if meta else 0
    content_type = str(meta.get("content_type") or "") if meta else ""
    playable = (
        meta is not None
        and size_bytes >= 10_000
        and (not content_type or content_type.startswith("audio/"))
    )
    return {
        "audio_key": audio_key,
        "exists_in_r2": meta is not None,
        "playable": playable,
        "size_bytes": size_bytes,
        "part": part,
    }


@router.post("/mocks/{mock_id}/ingest/audio")
async def upload_audio_route(
    mock_id: UUID,
    admin: Annotated[UserPublic, Depends(require_admin)],
    part: int = Query(..., ge=1, le=4),
    file: UploadFile = File(...),
):
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty audio file.")
    key = f"listening/{mock_id}/part-{part}/full.mp3"
    if len(content) < 10_000:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Audio file is too small to be a valid listening MP3.",
        )
    try:
        upload_object(key=key, body=content, content_type="audio/mpeg")
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    invalidate_listening_audio_caches(mock_test_id=mock_id)
    from app.admin.audit import log_admin_action

    log_admin_action(
        admin_id=admin.id,
        action="mock.audio_upload",
        resource_type="mock_test",
        resource_id=mock_id,
        metadata={"part": part, "key": key},
    )
    return {"ok": True, "audio_key": key}


@router.get("/mocks/{mock_id}/questions", response_model=QuestionTreeResponse)
def question_tree_route(
    mock_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> QuestionTreeResponse:
    return questions.get_question_tree(mock_id)


@router.get("/questions/{question_id}", response_model=AdminQuestionDetail)
def get_question_route(
    question_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> AdminQuestionDetail:
    return questions.get_question_detail(question_id)


@router.patch("/questions/{question_id}", response_model=AdminQuestionDetail)
def patch_question_route(
    question_id: UUID,
    body: PatchQuestionRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
) -> AdminQuestionDetail:
    return questions.patch_question(
        question_id=question_id, body=body, admin_id=admin.id
    )


@router.get("/speaking", response_model=SpeakingQueueResponse)
def list_speaking_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> SpeakingQueueResponse:
    return speaking.list_speaking_queue(
        status_filter=status, page=page, page_size=page_size
    )


@router.get("/speaking/{review_id}", response_model=SpeakingReviewDetail)
def get_speaking_route(
    review_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> SpeakingReviewDetail:
    return speaking.get_speaking_detail(review_id)


@router.patch("/speaking/{review_id}", response_model=SpeakingReviewDetail)
def patch_speaking_route(
    review_id: UUID,
    body: PatchSpeakingReviewRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
) -> SpeakingReviewDetail:
    return speaking.patch_speaking_review(
        review_id=review_id, body=body, admin_id=admin.id
    )


@router.patch("/speaking/{review_id}/approve", response_model=SpeakingReviewDetail)
def approve_speaking_route(
    review_id: UUID,
    body: ApproveSpeakingRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
) -> SpeakingReviewDetail:
    return speaking.approve_speaking_review(
        review_id=review_id, body=body, admin_id=admin.id
    )


@router.get("/audit", response_model=AuditLogResponse)
def list_audit_route(
    _super: Annotated[UserPublic, Depends(require_super_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> AuditLogResponse:
    return audit_routes.list_audit_logs(page=page, page_size=page_size)
