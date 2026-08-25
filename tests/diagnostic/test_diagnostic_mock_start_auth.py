"""Diagnostic mock UUID must require a full account on Writing/Speaking /start."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.diagnostic.constants import DIAGNOSTIC_MOCK_TEST_ID
from app.main import app
from app.schemas.test_engine import TestSummary
from app.speaking.schemas import SpeakingQuestionPublic, StartSpeakingResponse
from app.writing.schemas import StartWritingResponse, WritingTaskQuestion

M01 = UUID("a0000000-0000-4000-8000-000000000001")
STUDENT_ID = UUID("00000000-0000-4000-8000-0000000000a1")
GUEST_ID = UUID("00000000-0000-4000-8000-0000000000d1")
ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
Q1 = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
# Seeded by 20260825102000_diagnostic_speaking_manifest.sql
DIAGNOSTIC_SPEAKING_Q1 = UUID("d1000000-0000-4000-8000-000000000001")

FULL_ACCOUNT_DETAIL = "Sign in with a full account to continue the diagnostic."


def _student() -> UserPublic:
    return UserPublic(
        id=STUDENT_ID,
        email="student@example.com",
        full_name="Test Student",
        role="student",
        email_verified=True,
    )


def _guest() -> UserPublic:
    return UserPublic(
        id=GUEST_ID,
        email=None,
        full_name="Diagnostic Guest",
        role="guest",
    )


def _writing_start_response() -> StartWritingResponse:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return StartWritingResponse(
        attempt_id=ATTEMPT_ID,
        started_at=now,
        server_time=now,
        status="in_progress",
        part=1,
        duration_seconds=1200,
        resumed=False,
        test=TestSummary(id=DIAGNOSTIC_MOCK_TEST_ID, title="Free Diagnostic"),
        task=WritingTaskQuestion(
            id=Q1,
            question_number=1,
            question_type="task1_academic",
            prompt="Diagnostic writing prompt",
            part=1,
        ),
    )


def _diagnostic_speaking_start_response() -> StartSpeakingResponse:
    question = SpeakingQuestionPublic(
        id=DIAGNOSTIC_SPEAKING_Q1,
        question_number=1,
        question_type="speaking_part1",
        prompt="Tell me about your place.",
        part=1,
        kind="question",
        max_record_sec=120,
        duration_hint_sec=90,
        part_label="Part 1",
        video_url="/diagnostic/video/tell-me-about-your-place.mp4",
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return StartSpeakingResponse(
        attempt_id=ATTEMPT_ID,
        started_at=now,
        server_time=now,
        status="in_progress",
        part=1,
        duration_seconds=840,
        resumed=False,
        test=TestSummary(id=DIAGNOSTIC_MOCK_TEST_ID, title="Free Diagnostic"),
        question=question,
        questions=[question],
        manifest_hash="b" * 64,
        expected_response_count=1,
        student_name="Test Student",
    )


def _speaking_start_response() -> StartSpeakingResponse:
    question = SpeakingQuestionPublic(
        id=Q1,
        question_number=1,
        question_type="speaking_part1",
        prompt="Tell me about your hometown.",
        part=1,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return StartSpeakingResponse(
        attempt_id=ATTEMPT_ID,
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
        student_name="Test Student",
    )


def test_guest_writing_diagnostic_start_returns_403():
    app.dependency_overrides[get_current_user] = _guest
    client = TestClient(app)
    try:
        with patch(
            "app.writing.router.service.start_attempt",
            return_value=_writing_start_response(),
        ) as start_mock:
            res = client.post(f"/api/writing/{DIAGNOSTIC_MOCK_TEST_ID}/start")
        assert res.status_code == 403
        assert res.json()["detail"] == FULL_ACCOUNT_DETAIL
        start_mock.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_full_account_writing_diagnostic_start_succeeds():
    app.dependency_overrides[get_current_user] = _student
    client = TestClient(app)
    try:
        with (
            patch(
                "app.security.entitlements.resolve_entitlements",
                return_value={
                    "writing_skill": False,
                    "speaking_skill": False,
                    "full_skill_program": False,
                },
            ),
            patch(
                "app.writing.router.assert_skill_program_module_start",
                return_value=None,
            ),
            patch(
                "app.writing.router.service.start_attempt",
                return_value=_writing_start_response(),
            ) as start_mock,
        ):
            res = client.post(f"/api/writing/{DIAGNOSTIC_MOCK_TEST_ID}/start?part=1")
        assert res.status_code == 200
        body = res.json()
        assert body["attempt_id"] == str(ATTEMPT_ID)
        assert body["task"]["prompt"] == "Diagnostic writing prompt"
        start_mock.assert_called_once()
        assert start_mock.call_args.kwargs["mock_test_id"] == DIAGNOSTIC_MOCK_TEST_ID
        assert start_mock.call_args.kwargs["user_id"] == STUDENT_ID
    finally:
        app.dependency_overrides.clear()


def test_guest_speaking_diagnostic_start_returns_403_before_start_attempt():
    app.dependency_overrides[get_current_user] = _guest
    client = TestClient(app)
    try:
        with patch(
            "app.speaking.router.service.start_attempt",
            return_value=_diagnostic_speaking_start_response(),
        ) as start_mock:
            res = client.post(f"/api/speaking/{DIAGNOSTIC_MOCK_TEST_ID}/start")
        assert res.status_code == 403
        assert res.json()["detail"] == FULL_ACCOUNT_DETAIL
        start_mock.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_full_account_speaking_diagnostic_start_returns_200_with_question():
    """After diagnostic speaking seed, full-account /start succeeds with ≥1 question."""
    app.dependency_overrides[get_current_user] = _student
    client = TestClient(app)
    try:
        with (
            patch(
                "app.speaking.router.assert_skill_program_module_start",
                return_value=None,
            ),
            patch(
                "app.speaking.router.service.start_attempt",
                return_value=_diagnostic_speaking_start_response(),
            ) as start_mock,
            patch(
                "app.practice.writing_skill_mock.maybe_consume_after_new_mock_start",
                return_value=None,
            ),
        ):
            res = client.post(f"/api/speaking/{DIAGNOSTIC_MOCK_TEST_ID}/start")
        assert res.status_code == 200
        body = res.json()
        assert body["attempt_id"] == str(ATTEMPT_ID)
        assert isinstance(body.get("questions"), list)
        assert len(body["questions"]) >= 1
        assert body["questions"][0]["id"] == str(DIAGNOSTIC_SPEAKING_Q1)
        assert body["questions"][0]["question_type"] == "speaking_part1"
        assert body["questions"][0]["part"] == 1
        start_mock.assert_called_once()
        assert start_mock.call_args.kwargs["mock_test_id"] == DIAGNOSTIC_MOCK_TEST_ID
        assert start_mock.call_args.kwargs["user_id"] == STUDENT_ID
    finally:
        app.dependency_overrides.clear()


def test_diagnostic_speaking_seed_migration_defines_stable_question():
    """Migration seed must exist with pack-aligned Part 1 config (not M01 UUIDs)."""
    from pathlib import Path

    migrations = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
    path = migrations / "20260825102000_diagnostic_speaking_manifest.sql"
    assert path.is_file()
    sql = path.read_text(encoding="utf-8")
    assert "d1000000-0000-4000-8000-000000000001" in sql
    assert "d0000000-0000-4000-8000-000000000001" in sql
    assert "speaking_part1" in sql
    assert "tell-me-about-your-place.mp4" in sql
    assert "max_record_sec" in sql
    assert "c1000000-0000-4000-8000-000000000001" not in sql
    assert "a0000000-0000-4000-8000-000000000001" not in sql


def test_guest_non_diagnostic_writing_start_still_blocked_by_mock_access():
    app.dependency_overrides[get_current_user] = _guest
    client = TestClient(app)
    try:
        with patch(
            "app.writing.router.service.start_attempt",
            return_value=_writing_start_response(),
        ) as start_mock:
            res = client.post(f"/api/writing/{M01}/start")
        assert res.status_code == 403
        assert "free diagnostic test" in res.json()["detail"].lower()
        start_mock.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_full_account_non_diagnostic_writing_start_unchanged():
    app.dependency_overrides[get_current_user] = _student
    client = TestClient(app)
    try:
        with (
            patch("app.writing.router.assert_premium_mock_access", return_value=None),
            patch(
                "app.security.entitlements.resolve_entitlements",
                return_value={
                    "writing_skill": False,
                    "speaking_skill": False,
                    "full_skill_program": False,
                },
            ),
            patch(
                "app.writing.router.assert_skill_program_module_start",
                return_value=None,
            ),
            patch(
                "app.writing.router.service.start_attempt",
                return_value=_writing_start_response(),
            ) as start_mock,
        ):
            res = client.post(f"/api/writing/{M01}/start?part=1")
        assert res.status_code == 200
        start_mock.assert_called_once()
        assert start_mock.call_args.kwargs["mock_test_id"] == M01
    finally:
        app.dependency_overrides.clear()


def test_guest_non_diagnostic_speaking_start_still_blocked_by_mock_access():
    app.dependency_overrides[get_current_user] = _guest
    client = TestClient(app)
    try:
        with patch(
            "app.speaking.router.service.start_attempt",
            return_value=_speaking_start_response(),
        ) as start_mock:
            res = client.post(f"/api/speaking/{M01}/start")
        assert res.status_code == 403
        assert "free diagnostic test" in res.json()["detail"].lower()
        start_mock.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_full_account_non_diagnostic_speaking_start_unchanged():
    app.dependency_overrides[get_current_user] = _student
    client = TestClient(app)
    try:
        with (
            patch("app.speaking.router.assert_premium_mock_access", return_value=None),
            patch(
                "app.speaking.router.assert_skill_program_module_start",
                return_value=None,
            ),
            patch(
                "app.speaking.router.service.start_attempt",
                return_value=_speaking_start_response(),
            ) as start_mock,
            patch(
                "app.practice.writing_skill_mock.maybe_consume_after_new_mock_start",
                return_value=None,
            ),
        ):
            res = client.post(f"/api/speaking/{M01}/start?part=1")
        assert res.status_code == 200
        start_mock.assert_called_once()
        assert start_mock.call_args.kwargs["mock_test_id"] == M01
    finally:
        app.dependency_overrides.clear()
