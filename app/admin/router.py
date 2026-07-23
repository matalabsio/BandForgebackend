"""Admin API routes — all require admin role."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status

from app.admin import (
    ai_ops as admin_ai_ops,
    audit_routes,
    dashboard,
    diagnostics,
    mocks,
    mocks_ingest,
    payments as admin_payments,
    questions,
    review_analytics as admin_review_analytics,
    speaking,
    users,
    writing,
)
from app.admin.payments import (
    AdminPaymentMetrics,
    AdminPaymentsResponse,
    AdminSubscriptionsResponse,
)
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
    ApproveWritingRequest,
    PatchSpeakingReviewRequest,
    PatchWritingReviewRequest,
    AuditLogResponse,
    DashboardMetrics,
    DashboardOverview,
    DiagnosticDetail,
    DiagnosticQueueResponse,
    IngestPublishRequest,
    IngestPublishResponse,
    IngestValidateRequest,
    IngestValidateResponse,
    ReviewAnalyticsResponse,
    ReviewHistoryResponse,
    ReopenSpeakingReviewRequest,
    PatchAdminUserRequest,
    PatchDiagnosticSpeakingRequest,
    PatchMockStatusRequest,
    PatchQuestionRequest,
    QuestionTreeResponse,
    SendDiagnosticReportResponse,
    SpeakingQueueResponse,
    SpeakingReviewDetail,
    WritingQueueResponse,
    WritingReviewDetail,
)
from app.auth.schemas import UserPublic
from app.listening.service import invalidate_listening_audio_caches
from app.storage.r2 import object_exists, object_head, upload_object

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ai/metrics", response_model=admin_ai_ops.AiMetricsResponse)
def get_ai_metrics_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> admin_ai_ops.AiMetricsResponse:
    return admin_ai_ops.get_ai_metrics()


@router.get("/ai/health", response_model=admin_ai_ops.AiHealthResponse)
def get_ai_health_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> admin_ai_ops.AiHealthResponse:
    return admin_ai_ops.get_ai_health()


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


ADMIN_AUDIO_MAX_BYTES = 200 * 1024 * 1024


@router.post("/mocks/{mock_id}/ingest/audio")
async def upload_audio_route(
    request: Request,
    mock_id: UUID,
    admin: Annotated[UserPublic, Depends(require_admin)],
    part: int = Query(..., ge=1, le=4),
    file: UploadFile = File(...),
):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > ADMIN_AUDIO_MAX_BYTES:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Audio file is too large.",
                )
        except ValueError:
            pass
    content = await file.read()
    if len(content) > ADMIN_AUDIO_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio file is too large.",
        )
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


@router.post("/speaking/{review_id}/reopen", response_model=SpeakingReviewDetail)
def reopen_speaking_route(
    review_id: UUID,
    body: ReopenSpeakingReviewRequest,
    admin: Annotated[UserPublic, Depends(require_super_admin)],
) -> SpeakingReviewDetail:
    return speaking.reopen_speaking_review(
        review_id=review_id, body=body, admin_id=admin.id
    )


@router.get("/speaking/{review_id}/history", response_model=ReviewHistoryResponse)
def speaking_history_route(
    review_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> ReviewHistoryResponse:
    return audit_routes.get_review_history(
        resource_type="speaking_review",
        resource_id=review_id,
        actions=["speaking.draft", "speaking.approve", "speaking.reopen"],
    )


@router.get("/writing", response_model=WritingQueueResponse)
def list_writing_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> WritingQueueResponse:
    return writing.list_writing_queue(
        status_filter=status, page=page, page_size=page_size
    )


@router.get("/writing/{review_id}", response_model=WritingReviewDetail)
def get_writing_route(
    review_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
    source: Annotated[str, Query(pattern="^(mock|diagnostic)$")],
) -> WritingReviewDetail:
    return writing.get_writing_detail(review_id=review_id, source=source)  # type: ignore[arg-type]


@router.patch("/writing/{review_id}", response_model=WritingReviewDetail)
def patch_writing_route(
    review_id: UUID,
    body: PatchWritingReviewRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
    source: Annotated[str, Query(pattern="^(mock|diagnostic)$")],
) -> WritingReviewDetail:
    return writing.patch_writing_review(
        review_id=review_id,
        source=source,  # type: ignore[arg-type]
        body=body,
        admin_id=admin.id,
    )


@router.patch("/writing/{review_id}/approve", response_model=WritingReviewDetail)
def approve_writing_route(
    review_id: UUID,
    body: ApproveWritingRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
    source: Annotated[str, Query(pattern="^(mock|diagnostic)$")],
) -> WritingReviewDetail:
    return writing.approve_writing_review(
        review_id=review_id,
        source=source,  # type: ignore[arg-type]
        body=body,
        admin_id=admin.id,
    )


@router.post("/writing/{review_id}/retry-ai", response_model=WritingReviewDetail)
def retry_writing_ai_route(
    review_id: UUID,
    admin: Annotated[UserPublic, Depends(require_admin)],
    source: Annotated[str, Query(pattern="^(mock|diagnostic)$")] = "mock",
) -> WritingReviewDetail:
    return writing.retry_writing_ai_evaluation(
        review_id=review_id,
        source=source,  # type: ignore[arg-type]
        admin_id=admin.id,
    )


@router.get("/writing/{review_id}/history", response_model=ReviewHistoryResponse)
def writing_history_route(
    review_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
    source: Annotated[str, Query(pattern="^(mock|diagnostic)$")] = "mock",
) -> ReviewHistoryResponse:
    _ = source  # resource_id is unique; source kept for API symmetry with detail
    return audit_routes.get_review_history(
        resource_type="writing_review",
        resource_id=review_id,
        actions=["writing.draft", "writing.approve"],
    )


@router.get("/diagnostics", response_model=DiagnosticQueueResponse)
def list_diagnostics_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
    status: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> DiagnosticQueueResponse:
    return diagnostics.list_diagnostics(
        status_filter=status, q=q, page=page, page_size=page_size
    )


@router.get("/diagnostics/{diagnostic_id}", response_model=DiagnosticDetail)
def get_diagnostic_route(
    diagnostic_id: UUID,
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> DiagnosticDetail:
    return diagnostics.get_diagnostic_detail(diagnostic_id)


@router.patch("/diagnostics/{diagnostic_id}/speaking", response_model=DiagnosticDetail)
def patch_diagnostic_speaking_route(
    diagnostic_id: UUID,
    body: PatchDiagnosticSpeakingRequest,
    admin: Annotated[UserPublic, Depends(require_admin)],
) -> DiagnosticDetail:
    return diagnostics.patch_diagnostic_speaking(
        diagnostic_id=diagnostic_id, body=body, admin_id=admin.id
    )


@router.post(
    "/diagnostics/{diagnostic_id}/send-report",
    response_model=SendDiagnosticReportResponse,
)
async def send_diagnostic_report_route(
    diagnostic_id: UUID,
    admin: Annotated[UserPublic, Depends(require_admin)],
) -> SendDiagnosticReportResponse:
    return await diagnostics.send_diagnostic_report(
        diagnostic_id=diagnostic_id, admin_id=admin.id
    )


@router.get("/payments", response_model=AdminPaymentsResponse)
def list_payments_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> AdminPaymentsResponse:
    return admin_payments.list_payments(
        status_filter=status, page=page, page_size=page_size
    )


@router.get("/payments/metrics", response_model=AdminPaymentMetrics)
def payment_metrics_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> AdminPaymentMetrics:
    return admin_payments.get_payment_metrics()


@router.get("/subscriptions", response_model=AdminSubscriptionsResponse)
def list_subscriptions_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> AdminSubscriptionsResponse:
    return admin_payments.list_subscriptions(
        status_filter=status, page=page, page_size=page_size
    )


@router.get("/review-analytics", response_model=ReviewAnalyticsResponse)
def review_analytics_route(
    _admin: Annotated[UserPublic, Depends(require_admin)],
    module: Annotated[str, Query(pattern="^(speaking|writing|all)$")] = "all",
    days: int = Query(30, ge=1, le=365),
) -> ReviewAnalyticsResponse:
    return admin_review_analytics.get_review_analytics(
        module=module,  # type: ignore[arg-type]
        days=days,
    )


@router.get("/audit", response_model=AuditLogResponse)
def list_audit_route(
    admin: Annotated[UserPublic, Depends(require_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    action: str | None = None,
) -> AuditLogResponse:
    filtered = bool(resource_type or resource_id or action)
    if not filtered and admin.role != "super_admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Global audit log requires super_admin.",
        )
    return audit_routes.list_audit_logs(
        page=page,
        page_size=page_size,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
    )
