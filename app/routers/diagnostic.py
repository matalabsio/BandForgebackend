"""Diagnostic API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status

from app.auth.constants import (
    ACCESS_TOKEN_COOKIE,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_COOKIE,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from app.auth.dependencies import get_current_user, get_optional_user
from app.auth.schemas import AuthResponse, UserPublic
from app.config import get_settings
from app.diagnostic import service
from app.diagnostic.access import assert_full_account_for_productive_diagnostic
from app.diagnostic.complete import complete_diagnostic
from app.diagnostic.schemas import (
    DiagnosticCompleteRequest,
    DiagnosticCompleteResponse,
    DiagnosticLatestResponse,
    DiagnosticReviewSubmitRequest,
    DiagnosticReviewSubmitResponse,
)
from app.diagnostic.evaluation_schemas import (
    DiagnosticEvaluateWritingPendingResponse,
    DiagnosticEvaluateWritingRequest,
    DiagnosticWritingEvalStartResponse,
    DiagnosticWritingEvalStatusResponse,
)
from app.diagnostic.submit_review import submit_diagnostic_review
from app.diagnostic.writing_evaluator import (
    get_diagnostic_writing_status,
    start_diagnostic_writing_evaluation,
)
from app.security.rate_limit import (
    enforce_guest_session_rate_limit,
    enforce_submit_review_rate_limit,
)
from app.services import user_activity

router = APIRouter(prefix="/api/diagnostic", tags=["diagnostic"])


def _cookie_secure() -> bool:
    return get_settings().app_env == "production"


def _set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    secure = _cookie_secure()
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/",
    )


@router.get("/latest", response_model=DiagnosticLatestResponse)
def diagnostic_latest(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> DiagnosticLatestResponse:
    """Return the student's most recent completed diagnostic attempt."""
    rows = user_activity.list_user_diagnostics(current_user.id)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No diagnostic found.")
    row = rows[0]
    return DiagnosticLatestResponse(
        id=str(row["id"]),
        client_attempt_id=row.get("client_attempt_id"),
        status=row.get("status"),
        listening_band=row.get("listening_band"),
        reading_band=row.get("reading_band"),
        writing_band=row.get("writing_band"),
        speaking_band=row.get("speaking_band"),
        aggregate_band=row.get("aggregate_band"),
        completed_at=row.get("completed_at"),
        pack_version=row.get("pack_version"),
    )


@router.post("/complete", response_model=DiagnosticCompleteResponse)
async def diagnostic_complete(
    body: DiagnosticCompleteRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> DiagnosticCompleteResponse:
    """Persist diagnostic bands for a logged-in student (idempotent per client_attempt_id)."""
    if current_user.role == "guest":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Sign in with a full account to save diagnostic results.",
        )
    return complete_diagnostic(user_id=current_user.id, body=body)


@router.post("/submit-review", response_model=DiagnosticReviewSubmitResponse)
async def diagnostic_submit_review(
    body: DiagnosticReviewSubmitRequest,
    request: Request,
) -> DiagnosticReviewSubmitResponse:
    """Queue a marketing diagnostic for human examiner review (no login required)."""
    enforce_submit_review_rate_limit(request)
    return await submit_diagnostic_review(body)


@router.post("/evaluate-writing", response_model=None)
async def diagnostic_evaluate_writing(
    body: DiagnosticEvaluateWritingRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> DiagnosticWritingEvalStartResponse:
    """Enqueue diagnostic Writing AI evaluation (or return cache hit).

    Returns 200 with a completed evaluation on cache hit, otherwise 202 pending.
    Poll GET /evaluate-writing/status for the finished band.
    Full account required (mid-auth gate); guests receive 403.
    """
    assert_full_account_for_productive_diagnostic(user=current_user)
    result = await start_diagnostic_writing_evaluation(
        body, request, background_tasks
    )
    if isinstance(result, DiagnosticEvaluateWritingPendingResponse):
        response.status_code = status.HTTP_202_ACCEPTED
    else:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/evaluate-writing/status", response_model=None)
async def diagnostic_evaluate_writing_status(
    response: Response,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
    client_attempt_id: Annotated[str, Query(min_length=1, max_length=128)],
    essay_hash: Annotated[str | None, Query(max_length=128)] = None,
) -> DiagnosticWritingEvalStatusResponse:
    """Poll diagnostic Writing evaluation status for an attempt."""
    assert_full_account_for_productive_diagnostic(user=current_user)
    result = get_diagnostic_writing_status(
        client_attempt_id=client_attempt_id,
        essay_hash=essay_hash,
    )
    if isinstance(result, DiagnosticEvaluateWritingPendingResponse):
        response.status_code = status.HTTP_202_ACCEPTED
    else:
        response.status_code = status.HTTP_200_OK
    return result


@router.post("/guest-session", response_model=AuthResponse)
async def create_guest_session(
    request: Request,
    response: Response,
    current_user: Annotated[UserPublic | None, Depends(get_optional_user)] = None,
) -> AuthResponse:
    """Create or refresh a diagnostic guest JWT (no Google login required)."""
    enforce_guest_session_rate_limit(request)
    auth, refresh = await service.create_guest_session(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
        existing_user=current_user,
    )
    _set_auth_cookies(response, access_token=auth.access_token, refresh_token=refresh)
    return auth.model_copy(update={"refresh_token": refresh})
