"""Full-mock orchestration API."""

from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth.dependencies import get_current_user, get_current_user_timed
from app.auth.schemas import UserPublic
from app.config import get_settings
from app.diagnostic.access import assert_mock_access
from app.diagnostic.constants import DIAGNOSTIC_MOCK_TEST_ID
from app.security.entitlements import (
    assert_premium_mock_access,
    enforce_premium_mock_flags,
)
from app.schemas.mock_orchestrator import (
    InProgressMockAttempt,
    MockAttemptHistoryItem,
    MockAttemptHistoryLiteItem,
    MockAttemptProgress,
    MockAttemptSummary,
    MockCatalogItem,
    MockCheckpointResponse,
    ModuleReviewResponse,
    SpeakingModuleReviewResponse,
    StartMockRequest,
    StartMockResponse,
    WritingModuleReviewResponse,
)
from app.services import mock_orchestrator, module_review
from app.services import mock_orchestrator_repository as mock_repo
from app.services.mock_start_timing import MockStartTiming, elapsed_ms

router = APIRouter(prefix="/api/mock-attempts", tags=["mock-attempts"])


def _timing_log(
    route: str,
    started: float,
    status_code: int,
    *,
    extra: dict | None = None,
) -> None:
    payload: dict = {
        "route": route,
        "duration_ms": round((perf_counter() - started) * 1000, 2),
        "status": status_code,
    }
    if extra:
        payload.update(extra)
    else:
        payload["cache_hit"] = False
        payload["cache_layer"] = "none"
    print(json.dumps(payload))


@router.get("/catalog", response_model=list[MockCatalogItem])
def list_mock_catalog(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> list[MockCatalogItem]:
    _ = current_user
    include = get_settings().app_env.strip().lower() == "development"
    return mock_orchestrator.list_catalog(include_unpublished=include)


@router.post("", response_model=StartMockResponse)
async def start_mock_attempt(
    body: StartMockRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> StartMockResponse:
    timing = MockStartTiming()
    started = perf_counter()
    try:
        t0 = perf_counter()
        assert_mock_access(user=current_user, mock_test_id=body.mock_test_id)
        timing.access_guest_ms = elapsed_ms(t0)

        allow_unpublished = get_settings().app_env.strip().lower() == "development"
        t0 = perf_counter()
        if body.mock_test_id == DIAGNOSTIC_MOCK_TEST_ID:
            # Preserve prior behavior: no subscription reads for diagnostic UUID.
            start_ctx = await asyncio.to_thread(
                mock_repo.fetch_mock_start_context,
                user_id=current_user.id,
                mock_test_id=body.mock_test_id,
                allow_unpublished=allow_unpublished,
            )
            timing.fetch_start_context_ms = elapsed_ms(t0)
            timing.access_premium_ms = 0
        else:
            # One RPC: mock flags + modules + in-progress + subscription bit.
            start_ctx = await asyncio.to_thread(
                mock_repo.fetch_mock_start_gate_context,
                user_id=current_user.id,
                mock_test_id=body.mock_test_id,
                allow_unpublished=allow_unpublished,
            )
            timing.fetch_start_context_ms = elapsed_ms(t0)
            mock_row = (start_ctx or {}).get("mock_test")
            flags = (
                {
                    "is_free": bool(mock_row.get("is_free")),
                    "is_diagnostic": bool(mock_row.get("is_diagnostic")),
                }
                if isinstance(mock_row, dict)
                else None
            )
            t_gate = perf_counter()
            enforce_premium_mock_flags(
                user=current_user,
                mock_test_id=body.mock_test_id,
                flags=flags,
                subscription_active=(
                    None
                    if start_ctx is None or "has_active_subscription" not in start_ctx
                    else bool(start_ctx.get("has_active_subscription"))
                ),
            )
            timing.access_premium_ms = elapsed_ms(t_gate)

        response = await mock_orchestrator.start_mock(
            mock_test_id=body.mock_test_id,
            user_id=current_user.id,
            force_new=body.force_new,
            timing=timing,
            start_ctx=start_ctx,
        )
        timing.duration_ms = elapsed_ms(started)
        _timing_log(
            "POST /api/mock-attempts",
            started,
            200,
            extra=timing.to_log_fields(),
        )
        return response
    except Exception as exc:
        timing.duration_ms = elapsed_ms(started)
        status_code = (
            int(exc.status_code)
            if isinstance(exc, HTTPException)
            else 500
        )
        _timing_log(
            "POST /api/mock-attempts",
            started,
            status_code,
            extra=timing.to_log_fields(),
        )
        raise


@router.get("/session", response_model=MockAttemptProgress | None)
def get_mock_session_state(
    request: Request,
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user_timed)],
) -> MockAttemptProgress | None:
    assert_mock_access(user=current_user, mock_test_id=mock_test_id)
    assert_premium_mock_access(user=current_user, mock_test_id=mock_test_id)
    started = perf_counter()
    try:
        progress, timing = mock_orchestrator.get_mock_session_timed(
            mock_test_id=mock_test_id,
            user_id=current_user.id,
        )
        _timing_log(
            "/api/mock-attempts/session",
            started,
            200,
            extra={
                "cache_hit": timing["cache_hit"],
                "auth_ms": getattr(request.state, "auth_ms", None),
                "find_mock_ms": timing["find_mock_ms"],
                "progress_bundle_ms": timing["progress_bundle_ms"],
            },
        )
        return progress
    except Exception:
        _timing_log(
            "/api/mock-attempts/session",
            started,
            500,
            extra={
                "cache_hit": False,
                "auth_ms": getattr(request.state, "auth_ms", None),
                "find_mock_ms": 0,
                "progress_bundle_ms": 0,
            },
        )
        raise


@router.get("/in-progress", response_model=InProgressMockAttempt | None)
def get_in_progress_mock_attempt(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> InProgressMockAttempt | None:
    return mock_orchestrator.get_in_progress(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
    )


@router.get("/history-lite", response_model=list[MockAttemptHistoryLiteItem])
def list_mock_attempt_history_lite(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> list[MockAttemptHistoryLiteItem]:
    return mock_orchestrator.list_attempt_history_lite(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
    )


@router.get("/history", response_model=list[MockAttemptHistoryItem])
def list_mock_attempt_history(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> list[MockAttemptHistoryItem]:
    return mock_orchestrator.list_attempt_history(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
    )


@router.get("/{mock_attempt_id}/summary", response_model=MockAttemptSummary)
def get_mock_attempt_summary(
    mock_attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> MockAttemptSummary:
    return mock_orchestrator.get_summary(
        mock_attempt_id=mock_attempt_id,
        user_id=current_user.id,
    )


@router.get("/{mock_attempt_id}/checkpoint", response_model=MockCheckpointResponse)
def get_mock_checkpoint(
    mock_attempt_id: UUID,
    attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> MockCheckpointResponse:
    return mock_orchestrator.get_checkpoint(
        mock_attempt_id=mock_attempt_id,
        attempt_id=attempt_id,
        user_id=current_user.id,
    )


@router.get(
    "/{mock_attempt_id}/listening/module-review",
    response_model=ModuleReviewResponse,
)
def get_listening_module_review(
    mock_attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> ModuleReviewResponse:
    return module_review.get_module_review(
        mock_attempt_id=mock_attempt_id,
        module="listening",
        user_id=current_user.id,
    )


@router.get(
    "/{mock_attempt_id}/reading/module-review",
    response_model=ModuleReviewResponse,
)
def get_reading_module_review(
    mock_attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> ModuleReviewResponse:
    return module_review.get_module_review(
        mock_attempt_id=mock_attempt_id,
        module="reading",
        user_id=current_user.id,
    )


@router.get(
    "/{mock_attempt_id}/writing/module-review",
    response_model=WritingModuleReviewResponse,
)
async def get_writing_module_review(
    mock_attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> WritingModuleReviewResponse:
    return await module_review.get_writing_module_review(
        mock_attempt_id=mock_attempt_id,
        user_id=current_user.id,
    )


@router.get(
    "/{mock_attempt_id}/speaking/module-review",
    response_model=SpeakingModuleReviewResponse,
)
def get_speaking_module_review(
    mock_attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> SpeakingModuleReviewResponse:
    return module_review.get_speaking_module_review(
        mock_attempt_id=mock_attempt_id,
        user_id=current_user.id,
    )


@router.get("/{mock_attempt_id}", response_model=MockAttemptProgress)
def get_mock_attempt_progress(
    mock_attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> MockAttemptProgress:
    started = perf_counter()
    try:
        response = mock_orchestrator.get_progress(
            mock_attempt_id=mock_attempt_id,
            user_id=current_user.id,
        )
        _timing_log("/api/mock-attempts/{mock_attempt_id}", started, 200)
        return response
    except Exception:
        _timing_log("/api/mock-attempts/{mock_attempt_id}", started, 500)
        raise


@router.post("/{mock_attempt_id}/resume", response_model=StartMockResponse)
def resume_mock_attempt(
    mock_attempt_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> StartMockResponse:
    return mock_orchestrator.resume_mock(
        mock_attempt_id=mock_attempt_id,
        user_id=current_user.id,
    )
