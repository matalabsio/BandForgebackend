"""Diagnostic API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

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
from app.diagnostic.complete import complete_diagnostic
from app.diagnostic.schemas import (
    DiagnosticCompleteRequest,
    DiagnosticCompleteResponse,
    DiagnosticReviewSubmitRequest,
    DiagnosticReviewSubmitResponse,
)
from app.diagnostic.evaluation_schemas import (
    DiagnosticEvaluateWritingRequest,
    DiagnosticEvaluateWritingResponse,
)
from app.diagnostic.submit_review import submit_diagnostic_review
from app.diagnostic.writing_evaluator import evaluate_diagnostic_writing

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
) -> DiagnosticReviewSubmitResponse:
    """Queue a marketing diagnostic for human examiner review (no login required)."""
    return await submit_diagnostic_review(body)


@router.post("/evaluate-writing", response_model=DiagnosticEvaluateWritingResponse)
async def diagnostic_evaluate_writing(
    body: DiagnosticEvaluateWritingRequest,
    request: Request,
) -> DiagnosticEvaluateWritingResponse:
    """Evaluate diagnostic Writing via Groq (cached per essay / attempt)."""
    return await evaluate_diagnostic_writing(body, request)


@router.post("/guest-session", response_model=AuthResponse)
async def create_guest_session(
    request: Request,
    response: Response,
    current_user: Annotated[UserPublic | None, Depends(get_optional_user)] = None,
) -> AuthResponse:
    """Create or refresh a diagnostic guest JWT (no Google login required)."""
    auth, refresh = await service.create_guest_session(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
        existing_user=current_user,
    )
    _set_auth_cookies(response, access_token=auth.access_token, refresh_token=refresh)
    return auth.model_copy(update={"refresh_token": refresh})
