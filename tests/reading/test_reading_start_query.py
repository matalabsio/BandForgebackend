"""Reading /start must bind the passage query param (not legacy part=)."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.main import app
from app.reading.schemas import StartReadingResponse
from app.schemas.test_engine import TestSummary

M01 = UUID("a0000000-0000-4000-8000-000000000001")
USER = UUID("22222222-2222-4222-8222-222222222222")
MOCK_A = UUID("33333333-3333-4333-8333-333333333333")


def _user() -> UserPublic:
    return UserPublic(
        id=USER,
        email="reader@test.com",
        full_name="Reader",
        email_verified=True,
    )


def _start_response() -> StartReadingResponse:
    return StartReadingResponse(
        attempt_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        started_at=__import__("datetime").datetime(
            2026, 1, 1, tzinfo=__import__("datetime").UTC
        ),
        server_time=__import__("datetime").datetime(
            2026, 1, 1, tzinfo=__import__("datetime").UTC
        ),
        status="in_progress",
        duration_seconds=1800,
        resumed=False,
        test=TestSummary(id=M01, title="Mock"),
        passage_text="Passage",
        questions=[],
    )


def test_start_reading_binds_passage_query_param():
    app.dependency_overrides[get_current_user] = _user
    client = TestClient(app)
    try:
        with patch(
            "app.reading.router.service.start_attempt",
            return_value=_start_response(),
        ) as start_mock:
            res = client.post(
                f"/api/reading/{M01}/start"
                f"?include_questions=true&passage=2&mock_attempt_id={MOCK_A}",
            )
        assert res.status_code == 200
        assert start_mock.call_args.kwargs["part"] == 2
    finally:
        app.dependency_overrides.clear()


def test_start_reading_ignores_legacy_part_query_name():
    """part= without passage= must not override default passage 1."""
    app.dependency_overrides[get_current_user] = _user
    client = TestClient(app)
    try:
        with patch(
            "app.reading.router.service.start_attempt",
            return_value=_start_response(),
        ) as start_mock:
            res = client.post(
                f"/api/reading/{M01}/start"
                f"?include_questions=true&part=2&mock_attempt_id={MOCK_A}",
            )
        assert res.status_code == 200
        assert start_mock.call_args.kwargs["part"] == 1
    finally:
        app.dependency_overrides.clear()
