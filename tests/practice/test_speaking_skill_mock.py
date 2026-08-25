"""Speaking Skill mock unlock + quota consumption."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.auth.schemas import UserPublic
from app.practice.speaking_skill_mock import (
    COURSE_INCOMPLETE_DETAIL,
    MOCK_NOT_ALLOTTED_DETAIL,
    MOCK_QUOTA_EXHAUSTED_DETAIL,
    assert_speaking_skill_mock_access,
    assert_speaking_skill_mock_for_test,
    consume_speaking_skill_mock_quota,
    maybe_consume_speaking_after_new_mock_start,
    speaking_skill_mock_unlock_status,
)
from app.security.entitlements import Entitlements, enforce_premium_mock_flags

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
USAGE_ID = "usage-ss-1"
PLAN_ID = "plan-ss"
MOCK_SS = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_MOCK = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _ent(*, speaking_skill: bool = True, writing_skill: bool = False, fsp: bool = False) -> Entitlements:
    return {
        "plans": (
            (["speaking_skill"] if speaking_skill else [])
            + (["writing_skill"] if writing_skill else [])
            + (["full_skill_program"] if fsp else [])
        ),
        "skills": {
            "listening": fsp,
            "reading": fsp,
            "writing": writing_skill or fsp,
            "speaking": speaking_skill or fsp,
        },
        "writing_skill": writing_skill,
        "speaking_skill": speaking_skill,
        "full_skill_program": fsp,
    }


def _usage(**overrides):
    base = {
        "id": USAGE_ID,
        "user_id": str(USER_ID),
        "subscription_id": "sub-ss",
        "plan_id": PLAN_ID,
        "exam_module": None,
        "mocks_granted": 1,
        "mocks_used": 0,
    }
    base.update(overrides)
    return base


def _ctx(**usage_overrides):
    usage = _usage(**usage_overrides)
    return {
        "subscription_id": "sub-ss",
        "plan_id": PLAN_ID,
        "usage": usage,
    }


def _user() -> UserPublic:
    return UserPublic(
        id=USER_ID,
        email="s@example.com",
        full_name="S",
        phone="9876543210",
        target_band=7.0,
    )


def test_mock_locked_before_course_complete():
    with (
        patch(
            "app.practice.speaking_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.speaking_skill_mock.get_speaking_skill_course_context",
            return_value=_ctx(),
        ),
        patch(
            "app.practice.speaking_skill_mock.speaking_skill_course_completion",
            return_value=(3, 12, []),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_speaking_skill_mock_access(user_id=USER_ID)
        assert exc.value.status_code == 403
        detail = exc.value.detail
        assert isinstance(detail, dict)
        assert detail["message"] == COURSE_INCOMPLETE_DETAIL
        assert detail["completed"] == 3
        assert detail["required"] == 12


def test_mock_unlocked_at_12_of_12():
    with (
        patch(
            "app.practice.speaking_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.speaking_skill_mock.get_speaking_skill_course_context",
            return_value=_ctx(),
        ),
        patch(
            "app.practice.speaking_skill_mock.speaking_skill_course_completion",
            return_value=(12, 12, []),
        ),
        patch(
            "app.practice.speaking_skill_mock.resolve_speaking_skill_mock_test_id",
            return_value=MOCK_SS,
        ),
    ):
        status = speaking_skill_mock_unlock_status(user_id=USER_ID)
    assert status["unlocked"] is True
    assert status["completed"] == 12
    assert status["required"] == 12
    assert status["mock_test_id"] == MOCK_SS
    assert status["mocks_granted"] == 1
    assert status["mocks_used"] == 0
    assert status["exam_module"] is None


def test_new_mock_consumes_quota():
    with (
        patch(
            "app.practice.speaking_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.speaking_skill_mock.get_speaking_skill_course_context",
            return_value=_ctx(),
        ),
        patch(
            "app.practice.speaking_skill_mock.speaking_skill_course_completion",
            return_value=(12, 12, []),
        ),
        patch(
            "app.practice.speaking_skill_mock.resolve_speaking_skill_mock_test_id",
            return_value=MOCK_SS,
        ),
        patch(
            "app.practice.speaking_skill_mock.user_has_attempt_for_mock",
            return_value=False,
        ),
        patch(
            "app.practice.speaking_skill_mock.consume_speaking_skill_mock_quota",
            return_value=_usage(mocks_used=1),
        ) as consume,
    ):
        access = assert_speaking_skill_mock_for_test(
            user_id=USER_ID, mock_test_id=MOCK_SS
        )
        assert access["should_consume"] is True
        maybe_consume_speaking_after_new_mock_start(
            user_id=USER_ID, mock_test_id=MOCK_SS, created_new=True
        )
    consume.assert_called_once_with(usage_id=USAGE_ID)


def test_resumed_mock_does_not_consume_quota():
    with (
        patch(
            "app.practice.speaking_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.speaking_skill_mock.get_speaking_skill_course_context",
            return_value=_ctx(mocks_used=1),
        ),
        patch(
            "app.practice.speaking_skill_mock.speaking_skill_course_completion",
            return_value=(12, 12, []),
        ),
        patch(
            "app.practice.speaking_skill_mock.resolve_speaking_skill_mock_test_id",
            return_value=MOCK_SS,
        ),
        patch(
            "app.practice.speaking_skill_mock.user_has_attempt_for_mock",
            return_value=True,
        ),
        patch(
            "app.practice.speaking_skill_mock.consume_speaking_skill_mock_quota"
        ) as consume,
    ):
        access = assert_speaking_skill_mock_for_test(
            user_id=USER_ID, mock_test_id=MOCK_SS
        )
        assert access["should_consume"] is False
        maybe_consume_speaking_after_new_mock_start(
            user_id=USER_ID, mock_test_id=MOCK_SS, created_new=False
        )
    consume.assert_not_called()


def test_quota_exhausted_blocks_new_start():
    with (
        patch(
            "app.practice.speaking_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.speaking_skill_mock.get_speaking_skill_course_context",
            return_value=_ctx(mocks_used=1),
        ),
        patch(
            "app.practice.speaking_skill_mock.speaking_skill_course_completion",
            return_value=(12, 12, []),
        ),
        patch(
            "app.practice.speaking_skill_mock.resolve_speaking_skill_mock_test_id",
            return_value=MOCK_SS,
        ),
        patch(
            "app.practice.speaking_skill_mock.user_has_attempt_for_mock",
            return_value=False,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_speaking_skill_mock_for_test(
                user_id=USER_ID, mock_test_id=MOCK_SS
            )
        assert exc.value.status_code == 403
        assert exc.value.detail == MOCK_QUOTA_EXHAUSTED_DETAIL


def test_non_allotted_mock_denied():
    with (
        patch(
            "app.practice.speaking_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.speaking_skill_mock.get_speaking_skill_course_context",
            return_value=_ctx(),
        ),
        patch(
            "app.practice.speaking_skill_mock.speaking_skill_course_completion",
            return_value=(12, 12, []),
        ),
        patch(
            "app.practice.speaking_skill_mock.resolve_speaking_skill_mock_test_id",
            return_value=MOCK_SS,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_speaking_skill_mock_for_test(
                user_id=USER_ID, mock_test_id=OTHER_MOCK
            )
        assert exc.value.status_code == 403
        assert exc.value.detail == MOCK_NOT_ALLOTTED_DETAIL


def test_premium_gate_routes_speaking_skill_pack():
    with (
        patch(
            "app.security.entitlements.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.speaking_skill_mock.assert_speaking_skill_mock_for_test",
            return_value={"usage_id": USAGE_ID},
        ) as assert_ss,
    ):
        enforce_premium_mock_flags(
            user=_user(),
            mock_test_id=UUID(MOCK_SS),
            flags={"is_free": False, "is_diagnostic": False},
        )
    assert_ss.assert_called_once()


def test_fsp_still_uses_subscription_gate():
    with (
        patch(
            "app.security.entitlements.resolve_entitlements",
            return_value=_ent(fsp=True, speaking_skill=True),
        ),
        patch(
            "app.security.entitlements.has_active_subscription",
            return_value=True,
        ),
        patch(
            "app.practice.speaking_skill_mock.assert_speaking_skill_mock_for_test"
        ) as assert_ss,
    ):
        enforce_premium_mock_flags(
            user=_user(),
            mock_test_id=UUID(MOCK_SS),
            flags={"is_free": False, "is_diagnostic": False},
        )
    assert_ss.assert_not_called()


def test_consume_quota_atomic_helper():
    with patch(
        "app.payments.repository.consume_user_program_mock_quota_atomic",
        return_value=_usage(mocks_used=1),
    ):
        row = consume_speaking_skill_mock_quota(usage_id=USAGE_ID)
    assert row["mocks_used"] == 1
