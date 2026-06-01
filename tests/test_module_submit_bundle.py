"""Tests for Phase 2b submit bundle helper."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.db.module_submit_bundle import persist_module_submit_bundle

ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")


def test_persist_uses_rpc_when_available():
    rpc_row = {
        "id": str(ATTEMPT_ID),
        "user_id": str(USER_ID),
        "mock_test_id": "a0000000-0000-4000-8000-000000000001",
        "status": "completed",
        "completed_at": "2026-01-01T00:00:00+00:00",
    }
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.return_value.data = rpc_row

    with patch("app.db.module_submit_bundle.get_supabase", return_value=mock_client):
        result = persist_module_submit_bundle(
            attempt_id=ATTEMPT_ID,
            user_id=USER_ID,
            module="listening",
            completed_at=datetime.now(UTC),
            answer_rows=[{"question_id": "q1", "user_answer": "a", "is_correct": True}],
            raw_score=1,
            total_count=1,
            band=9.0,
            skill_breakdown={},
        )

    assert result["status"] == "completed"
    mock_client.rpc.assert_called_once()
    assert mock_client.rpc.call_args[0][0] == "persist_module_submit_bundle"


def test_persist_fallback_on_rpc_failure():
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.side_effect = Exception("function not found")

    with (
        patch("app.db.module_submit_bundle.get_supabase", return_value=mock_client),
        patch(
            "app.db.module_submit_bundle._persist_module_submit_sequential",
            return_value={"id": str(ATTEMPT_ID), "status": "completed"},
        ) as sequential,
    ):
        result = persist_module_submit_bundle(
            attempt_id=ATTEMPT_ID,
            user_id=USER_ID,
            module="reading",
            completed_at=datetime.now(UTC),
            answer_rows=[],
            raw_score=0,
            total_count=10,
            band=5.0,
        )

    assert result["status"] == "completed"
    sequential.assert_called_once()


def test_persist_maps_attempt_not_in_progress():
    mock_client = MagicMock()
    mock_client.rpc.return_value.execute.side_effect = Exception("attempt_not_in_progress")

    with patch("app.db.module_submit_bundle.get_supabase", return_value=mock_client):
        with pytest.raises(HTTPException) as exc:
            persist_module_submit_bundle(
                attempt_id=ATTEMPT_ID,
                user_id=USER_ID,
                module="writing",
                completed_at=datetime.now(UTC),
                answer_rows=[],
                raw_score=100,
                total_count=100,
                band=6.0,
            )
    assert exc.value.status_code == 409
