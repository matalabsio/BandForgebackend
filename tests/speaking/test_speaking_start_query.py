"""Speaking /start query behavior for plan-mode parity."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.main import app
from app.schemas.test_engine import TestSummary
from app.speaking.schemas import SpeakingQuestionPublic, StartSpeakingResponse

M01 = UUID("a0000000-0000-4000-8000-000000000001")
USER = UUID("22222222-2222-4222-8222-222222222222")
MOCK_A = UUID("33333333-3333-4333-8333-333333333333")
Q1 = UUID("44444444-4444-4444-8444-444444444444")


def _user() -> UserPublic:
    return UserPublic(
        id=USER,
        email="speaker@test.com",
        full_name="Speaker",
        email_verified=True,
    )


def _start_response() -> StartSpeakingResponse:
    question = SpeakingQuestionPublic(
        id=Q1,
        question_number=1,
        question_type="speaking_part1",
        prompt="Tell me about your hometown.",
        part=1,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return StartSpeakingResponse(
        attempt_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        started_at=now,
        server_time=now,
        status="in_progress",
        part=1,
        duration_seconds=840,
        resumed=False,
        test=TestSummary(id=M01, title="Mock"),
        question=question,
        questions=[question],
        manifest_hash="a" * 64,
        expected_response_count=1,
        student_name="Speaker",
    )


def test_start_speaking_forwards_from_plan_to_skill_gate():
    app.dependency_overrides[get_current_user] = _user
    client = TestClient(app)
    try:
        with (
            patch("app.speaking.router.assert_mock_access", return_value=None),
            patch("app.speaking.router.assert_premium_mock_access", return_value=None),
            patch("app.speaking.router.service.start_attempt", return_value=_start_response()),
            patch("app.speaking.router.assert_skill_program_module_start", return_value=None) as gate_mock,
        ):
            res = client.post(
                f"/api/speaking/{M01}/start"
                f"?part=1&mock_attempt_id={MOCK_A}"
                "&skill_context=speaking&from_plan=true",
            )
        assert res.status_code == 200
        assert gate_mock.call_args.kwargs["skill_context"] == "speaking"
        assert gate_mock.call_args.kwargs["from_plan"] is True
    finally:
        app.dependency_overrides.clear()
