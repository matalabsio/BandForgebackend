"""Diagnostic completion refreshes the learning-profile snapshot."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.diagnostic.complete import complete_diagnostic
from app.diagnostic.schemas import DiagnosticCompleteRequest


def test_complete_diagnostic_schedules_profile_refresh():
    user_id = uuid4()
    mock_sb = MagicMock()
    existing = MagicMock()
    existing.data = None
    inserted = MagicMock()
    inserted.data = [{"id": "diag-1"}]
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        existing
    )
    mock_sb.table.return_value.insert.return_value.execute.return_value = inserted

    body = DiagnosticCompleteRequest(
        client_attempt_id="attempt-abc",
        listening_band=6.5,
        reading_band=6.0,
    )

    with (
        patch("app.diagnostic.complete.get_supabase", return_value=mock_sb),
        patch(
            "app.learning.service.schedule_profile_refresh"
        ) as schedule,
    ):
        result = complete_diagnostic(user_id=user_id, body=body)

    assert result.id == "diag-1"
    assert result.client_attempt_id == "attempt-abc"
    schedule.assert_called_once_with(user_id)
