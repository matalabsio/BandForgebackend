"""Tests for skill-program mock gate on module/test starts."""

from __future__ import annotations

import asyncio
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.skill_program_gate import assert_skill_program_module_start
from app.schemas.test_engine import StartAttemptRequest

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")


def test_assert_skill_program_module_start_no_context():
    assert_skill_program_module_start(user_id=USER_ID, skill_context=None)


def test_assert_skill_program_module_start_invalid_skill():
    with pytest.raises(HTTPException) as exc:
        assert_skill_program_module_start(user_id=USER_ID, skill_context="invalid")
    assert exc.value.status_code == 400


def test_assert_skill_program_module_start_locked():
    with (
        patch("app.security.entitlements.has_full_skill_program", return_value=True),
        patch(
            "app.practice.service.assert_skill_mock_access",
            side_effect=HTTPException(status_code=403, detail="locked"),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_skill_program_module_start(user_id=USER_ID, skill_context="listening")
        assert exc.value.status_code == 403


def test_assert_skill_program_module_start_unlocked():
    with (
        patch("app.security.entitlements.has_full_skill_program", return_value=True),
        patch("app.practice.service.assert_skill_mock_access", return_value=None),
    ):
        assert_skill_program_module_start(user_id=USER_ID, skill_context="reading")


def test_assert_skill_program_module_start_from_plan_skips_mock_unlock():
    with (
        patch("app.security.entitlements.has_full_skill_program", return_value=True),
        patch(
            "app.practice.service.assert_skill_mock_access",
            side_effect=HTTPException(status_code=403, detail="locked"),
        ) as mock_unlock,
    ):
        assert_skill_program_module_start(
            user_id=USER_ID,
            skill_context="writing",
            from_plan=True,
        )
        mock_unlock.assert_not_called()


def test_start_attempt_request_accepts_skill_context():
    body = StartAttemptRequest(module="listening", skill_context="listening")
    assert body.skill_context == "listening"
