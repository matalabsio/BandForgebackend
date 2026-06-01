"""Full-mock orchestration API."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.config import get_settings
from app.schemas.mock_orchestrator import (
    InProgressMockAttempt,
    MockAttemptHistoryItem,
    MockAttemptHistoryLiteItem,
    MockAttemptProgress,
    MockAttemptSummary,
    MockCatalogItem,
    MockCheckpointResponse,
    StartMockRequest,
    StartMockResponse,
)
from app.services import mock_orchestrator

router = APIRouter(prefix="/api/mock-attempts", tags=["mock-attempts"])


def _timing_log(route: str, started: float, status_code: int) -> None:
    print(
        json.dumps(
            {
                "route": route,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
                "cache_hit": False,
                "cache_layer": "none",
                "status": status_code,
            }
        )
    )


@router.get("/catalog", response_model=list[MockCatalogItem])
def list_mock_catalog(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> list[MockCatalogItem]:
    _ = current_user
    include = get_settings().app_env.strip().lower() == "development"
    return mock_orchestrator.list_catalog(include_unpublished=include)


@router.post("", response_model=StartMockResponse)
def start_mock_attempt(
    body: StartMockRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> StartMockResponse:
    return mock_orchestrator.start_mock(
        mock_test_id=body.mock_test_id,
        user_id=current_user.id,
        force_new=body.force_new,
    )


@router.get("/session", response_model=MockAttemptProgress | None)
def get_mock_session_state(
    mock_test_id: UUID,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> MockAttemptProgress | None:
    return mock_orchestrator.get_mock_session(
        mock_test_id=mock_test_id,
        user_id=current_user.id,
    )


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
