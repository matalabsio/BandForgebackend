"""Partial profile update: phone problems become warnings, other fields persist."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.auth.schemas import UpdateProfileRequest, UpdateProfileResponse, UserPublic
from app.auth.service import update_user_profile


def test_update_user_profile_phone_clash_returns_warning_and_persists_other_fields():
    user_id = uuid4()
    body = UpdateProfileRequest(
        full_name="Paid Student",
        phone="9517593294",
        target_band=7.0,
        exam_date="2026-08-19",
    )

    mock_sb = MagicMock()
    clash = MagicMock()
    clash.data = [{"id": str(uuid4())}]
    mock_sb.table.return_value.select.return_value.eq.return_value.neq.return_value.limit.return_value.execute.return_value = (
        clash
    )

    returned = UserPublic(
        id=user_id,
        email="student@example.com",
        full_name="Paid Student",
        phone=None,
        target_band=7.0,
        role="student",
    )

    with (
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.get_user_by_id",
            new=AsyncMock(return_value=returned),
        ),
    ):
        result = asyncio.run(update_user_profile(user_id=user_id, body=body))

    assert isinstance(result, UpdateProfileResponse)
    assert result.warnings["phone"] == (
        "This phone number is already linked to another account."
    )
    assert result.user.full_name == "Paid Student"
    assert result.user.target_band == 7.0

    update_payload = mock_sb.table.return_value.update.call_args[0][0]
    assert update_payload["full_name"] == "Paid Student"
    assert update_payload["target_band"] == 7.0
    assert update_payload["exam_date"] == "2026-08-19"
    assert "phone" not in update_payload


def test_update_user_profile_invalid_phone_returns_format_warning():
    user_id = uuid4()
    body = UpdateProfileRequest(
        full_name="Student",
        phone="123",
        target_band=6.5,
        exam_date="2026-09-01",
    )

    mock_sb = MagicMock()
    returned = UserPublic(
        id=user_id,
        email="student@example.com",
        full_name="Student",
        phone="+919876543210",
        target_band=6.5,
        role="student",
    )

    with (
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.get_user_by_id",
            new=AsyncMock(return_value=returned),
        ),
    ):
        result = asyncio.run(update_user_profile(user_id=user_id, body=body))

    assert result.warnings["phone"] == "Enter a valid 10-digit Indian mobile number."
    update_payload = mock_sb.table.return_value.update.call_args[0][0]
    assert update_payload["full_name"] == "Student"
    assert update_payload["exam_date"] == "2026-09-01"
    assert "phone" not in update_payload
    mock_sb.table.return_value.select.assert_not_called()


def test_update_user_profile_sets_phone_when_free():
    user_id = uuid4()
    body = UpdateProfileRequest(
        full_name="Solo Student",
        phone="9876543210",
        target_band=6.5,
        exam_date="2026-09-01",
    )

    mock_sb = MagicMock()
    clash = MagicMock()
    clash.data = []
    mock_sb.table.return_value.select.return_value.eq.return_value.neq.return_value.limit.return_value.execute.return_value = (
        clash
    )

    returned = UserPublic(
        id=user_id,
        email="solo@example.com",
        full_name="Solo Student",
        phone="+919876543210",
        target_band=6.5,
        role="student",
    )

    with (
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.get_user_by_id",
            new=AsyncMock(return_value=returned),
        ),
    ):
        result = asyncio.run(update_user_profile(user_id=user_id, body=body))

    assert result.warnings == {}
    update_payload = mock_sb.table.return_value.update.call_args[0][0]
    assert update_payload["phone"] == "+919876543210"
    assert update_payload["exam_date"] == "2026-09-01"


def test_update_user_profile_writes_ielts_purpose_and_goal():
    user_id = uuid4()
    body = UpdateProfileRequest(
        full_name="Dream Student",
        target_band=7.0,
        ielts_purpose="university",
        ielts_goal="study_abroad",
    )

    mock_sb = MagicMock()
    returned = UserPublic(
        id=user_id,
        email="dream@example.com",
        full_name="Dream Student",
        target_band=7.0,
        ielts_purpose="university",
        ielts_goal="study_abroad",
        role="student",
    )

    with (
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.get_user_by_id",
            new=AsyncMock(return_value=returned),
        ),
    ):
        result = asyncio.run(update_user_profile(user_id=user_id, body=body))

    assert result.user.ielts_purpose == "university"
    assert result.user.ielts_goal == "study_abroad"
    update_payload = mock_sb.table.return_value.update.call_args[0][0]
    assert update_payload["ielts_purpose"] == "university"
    assert update_payload["ielts_goal"] == "study_abroad"


def test_update_user_profile_omits_ielts_fields_when_unset():
    user_id = uuid4()
    body = UpdateProfileRequest(full_name="No Dream", target_band=6.5)

    mock_sb = MagicMock()
    returned = UserPublic(
        id=user_id,
        email="nodream@example.com",
        full_name="No Dream",
        target_band=6.5,
        role="student",
    )

    with (
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch(
            "app.auth.service.get_user_by_id",
            new=AsyncMock(return_value=returned),
        ),
    ):
        asyncio.run(update_user_profile(user_id=user_id, body=body))

    update_payload = mock_sb.table.return_value.update.call_args[0][0]
    assert "ielts_purpose" not in update_payload
    assert "ielts_goal" not in update_payload
