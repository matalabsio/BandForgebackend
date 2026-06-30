"""Admin diagnostic funnel tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.admin.diagnostics import (
    aggregate_diagnostic_band,
    list_diagnostics,
    patch_diagnostic_speaking,
    send_diagnostic_report,
)
from app.admin.schemas import PatchDiagnosticSpeakingRequest, HumanCriteriaScores

DIAG_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ADMIN_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _table_chain(data=None, count=None):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.neq.return_value = chain
    chain.or_.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.limit.return_value = chain
    chain.update.return_value = chain
    result = MagicMock()
    result.data = data if data is not None else []
    result.count = count
    chain.execute.return_value = result
    return chain


def test_aggregate_diagnostic_band_rounds_to_half():
    assert aggregate_diagnostic_band(6.0, 6.5, 5.5, 5.0) == 6.0


def test_list_diagnostics_returns_items():
    row = {
        "id": str(DIAG_ID),
        "full_name": "Aarav Sharma",
        "email": "aarav@example.com",
        "phone": "9876543210",
        "goal_label": "Australian PR",
        "target_band": 7.0,
        "listening_band": 6.0,
        "reading_band": 6.5,
        "writing_band": 5.5,
        "speaking_band": 5.0,
        "speaking_human_band": None,
        "aggregate_band": 5.8,
        "status": "pending_review",
        "report_email_sent_at": None,
        "created_at": "2026-06-30T10:00:00+00:00",
    }
    list_chain = _table_chain([row], count=1)
    pending_chain = _table_chain(count=1)
    mock_client = MagicMock()

    def table_side_effect(name):
        if name == "diagnostic_review_submissions":
            if table_side_effect.calls == 0:
                table_side_effect.calls += 1
                return list_chain
            return pending_chain
        return _table_chain()

    table_side_effect.calls = 0
    mock_client.table.side_effect = table_side_effect

    with patch("app.admin.diagnostics.get_supabase", return_value=mock_client):
        res = list_diagnostics(page=1, page_size=25)

    assert res.total == 1
    assert res.items[0].full_name == "Aarav Sharma"
    assert res.pending_count == 1


def test_send_diagnostic_report_requires_email():
    row = {
        "id": str(DIAG_ID),
        "email": None,
        "speaking_human_band": 6.0,
        "human_band": 5.5,
        "writing_band": 5.5,
        "listening_band": 6.0,
        "reading_band": 6.5,
        "full_name": "Test",
        "goal_label": None,
        "target_band": 7.0,
        "speaking_reviewer_notes": None,
        "diagnostic_ai_evaluations": None,
    }
    chain = _table_chain([row])
    mock_client = MagicMock()
    mock_client.table.return_value = chain

    with patch("app.admin.diagnostics.get_supabase", return_value=mock_client):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                send_diagnostic_report(diagnostic_id=DIAG_ID, admin_id=ADMIN_ID)
            )
    assert exc.value.status_code == 400


def test_send_diagnostic_report_success():
    row = {
        "id": str(DIAG_ID),
        "email": "student@example.com",
        "speaking_human_band": 6.0,
        "human_band": None,
        "writing_band": 5.5,
        "listening_band": 6.0,
        "reading_band": 6.5,
        "full_name": "Test Student",
        "goal_label": "UK study",
        "target_band": 6.5,
        "speaking_reviewer_notes": "Good fluency",
        "diagnostic_ai_evaluations": {"feedback": {"strengths": ["Clear structure"]}},
    }
    select_chain = _table_chain([row])
    update_chain = _table_chain()
    mock_client = MagicMock()
    calls = {"n": 0}

    def table_side_effect(name):
        if calls["n"] == 0:
            calls["n"] += 1
            return select_chain
        return update_chain

    mock_client.table.side_effect = table_side_effect

    with (
        patch("app.admin.diagnostics.get_supabase", return_value=mock_client),
        patch("app.admin.diagnostics.log_admin_action"),
        patch(
            "app.admin.diagnostics.send_diagnostic_report_email",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        res = asyncio.run(
            send_diagnostic_report(diagnostic_id=DIAG_ID, admin_id=ADMIN_ID)
        )

    assert res.ok is True
    assert res.recipient == "student@example.com"


def test_patch_diagnostic_speaking_sets_band():
    existing_chain = _table_chain([{"id": str(DIAG_ID)}])
    update_chain = _table_chain()
    detail_row = {
        "id": str(DIAG_ID),
        "client_attempt_id": "attempt-1",
        "full_name": "Test",
        "email": "t@example.com",
        "phone": "9876543210",
        "goal_label": None,
        "target_band": 7.0,
        "listening_band": 6.0,
        "reading_band": 6.5,
        "writing_band": 5.5,
        "human_band": None,
        "speaking_band": 5.0,
        "speaking_human_band": 6.0,
        "aggregate_band": 5.8,
        "status": "pending_review",
        "speaking_human_criteria_scores": {
            "fluency": 6.0,
            "lexical": 6.0,
            "grammar": 6.0,
            "pronunciation": 6.0,
        },
        "speaking_reviewer_notes": "ok",
        "speaking_reviewed_at": datetime.now(timezone.utc).isoformat(),
        "report_email_sent_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_at": None,
        "answers": {},
        "diagnostic_ai_evaluations": None,
    }
    detail_chain = _table_chain([detail_row])
    mock_client = MagicMock()
    call_n = {"n": 0}

    def table_side_effect(name):
        n = call_n["n"]
        call_n["n"] += 1
        if n == 0:
            return existing_chain
        if n == 1:
            return update_chain
        return detail_chain

    mock_client.table.side_effect = table_side_effect

    body = PatchDiagnosticSpeakingRequest(
        human_criteria_scores=HumanCriteriaScores(
            fluency=6.0,
            lexical=6.0,
            grammar=6.0,
            pronunciation=6.0,
        ),
        reviewer_notes="Solid Part 2",
    )

    with (
        patch("app.admin.diagnostics.get_supabase", return_value=mock_client),
        patch("app.admin.diagnostics.log_admin_action"),
    ):
        detail = patch_diagnostic_speaking(
            diagnostic_id=DIAG_ID, body=body, admin_id=ADMIN_ID
        )

    assert detail.speaking_human_band == 6.0
