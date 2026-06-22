"""Admin user list and overview tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.admin.schemas import (
    AdminUserActivityStats,
    AdminUserDetail,
    AdminUserListItem,
    AdminUserOverview,
)
from app.diagnostic.schemas import DiagnosticCompleteRequest
from app.admin.users import _admin_role
from app.services.user_activity import batch_user_list_aggregates


def test_admin_role_maps_unknown_to_student():
    assert _admin_role("guest") == "guest"
    assert _admin_role(None) == "student"
    assert _admin_role("weird") == "student"


def test_batch_user_list_aggregates_empty():
    assert batch_user_list_aggregates([]) == {}


def test_diagnostic_complete_request_requires_client_attempt_id():
    with pytest.raises(ValidationError):
        DiagnosticCompleteRequest(client_attempt_id="")


def test_diagnostic_complete_request_accepts_bands():
    body = DiagnosticCompleteRequest(
        client_attempt_id="diag-123",
        listening_band=6.5,
        reading_band=7.0,
        aggregate_band=6.5,
        completed_at=datetime.now(UTC),
    )
    assert body.client_attempt_id == "diag-123"
    assert body.listening_band == 6.5


def test_admin_user_overview_schema_roundtrip():
    user_id = uuid4()
    now = datetime.now(UTC)
    overview = AdminUserOverview(
        profile=AdminUserDetail(
            id=user_id,
            email="student@test.com",
            full_name="Test Student",
            created_at=now,
            mock_attempt_count=2,
            completed_mock_count=1,
        ),
        stats=AdminUserActivityStats(
            total_attempts=4,
            completed_attempts=3,
            in_progress_attempts=1,
            average_band=6.5,
            best_band=7.0,
            last_activity_at=now,
            current_streak=2,
            longest_streak=5,
        ),
        mock_sessions=[],
        recent_modules=[],
        in_progress=[],
        diagnostics=[],
        speaking_reviews=[],
    )
    parsed = AdminUserOverview.model_validate(overview.model_dump(mode="json"))
    assert parsed.profile.email == "student@test.com"
    assert parsed.stats.best_band == 7.0


def test_admin_user_list_item_includes_aggregates():
    item = AdminUserListItem(
        id=uuid4(),
        email="a@test.com",
        created_at=datetime.now(UTC),
        mock_attempt_count=3,
        completed_mock_count=1,
        last_activity_at=datetime.now(UTC),
        best_band=7.5,
    )
    assert item.completed_mock_count == 1
    assert item.best_band == 7.5


def test_list_user_diagnostics_returns_empty_when_table_missing(monkeypatch):
    from postgrest.exceptions import APIError

    from app.services import user_activity

    def _raise_missing(*_args, **_kwargs):
        raise APIError(
            {
                "message": "Could not find the table 'public.diagnostic_attempts' in the schema cache",
                "code": "PGRST205",
            }
        )

    monkeypatch.setattr(user_activity, "execute_with_retry", _raise_missing)
    assert user_activity.list_user_diagnostics(uuid4()) == []
