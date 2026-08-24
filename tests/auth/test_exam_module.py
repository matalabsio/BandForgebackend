"""FSP Writing track: users.exam_module profile + purpose recommendation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.auth.exam_module import (
    recommend_exam_module,
    requires_explicit_exam_module_choice,
)
from app.auth.schemas import UpdateProfileRequest, UserPublic
from app.auth.service import update_user_profile


# ── Recommendation ──────────────────────────────────────────────────────────


def test_university_recommends_academic():
    assert recommend_exam_module("university") == "academic"


def test_immigration_recommends_general_training():
    assert recommend_exam_module("immigration") == "general_training"


def test_professional_recommends_general_training():
    assert recommend_exam_module("professional") == "general_training"
    assert requires_explicit_exam_module_choice("professional") is False


def test_general_recommends_general_training():
    assert recommend_exam_module("general") == "general_training"
    assert requires_explicit_exam_module_choice("general") is False


def test_recommendation_is_soft_university_may_choose_gt():
    """Purpose recommends Academic; explicit GT choice is still allowed by API."""
    assert recommend_exam_module("university") == "academic"
    body = UpdateProfileRequest(
        full_name="Student",
        exam_module="general_training",
        ielts_purpose="university",
    )
    assert body.exam_module == "general_training"
    assert body.ielts_purpose == "university"


def test_recommendation_is_soft_immigration_may_choose_academic():
    assert recommend_exam_module("immigration") == "general_training"
    body = UpdateProfileRequest(
        full_name="Student",
        exam_module="academic",
        ielts_purpose="immigration",
    )
    assert body.exam_module == "academic"
    assert body.ielts_purpose == "immigration"


# ── Profile validation ──────────────────────────────────────────────────────


def test_exam_module_academic_accepted():
    body = UpdateProfileRequest(full_name="A", exam_module="academic")
    assert body.exam_module == "academic"


def test_exam_module_general_training_accepted():
    body = UpdateProfileRequest(full_name="A", exam_module="general_training")
    assert body.exam_module == "general_training"


@pytest.mark.parametrize(
    "bad",
    ["Academic", "GT", "general", "immigration", "university", "foo", "ACADEMIC"],
)
def test_exam_module_invalid_rejected(bad: str):
    with pytest.raises(ValidationError):
        UpdateProfileRequest(full_name="A", exam_module=bad)  # type: ignore[arg-type]


def test_exam_module_null_omitted_from_request_is_valid():
    body = UpdateProfileRequest(full_name="Legacy")
    assert body.exam_module is None


def test_exam_module_empty_string_becomes_none():
    body = UpdateProfileRequest(full_name="Legacy", exam_module="")  # type: ignore[arg-type]
    assert body.exam_module is None


# ── Persistence ─────────────────────────────────────────────────────────────


def test_update_profile_persists_exam_module_academic():
    user_id = uuid4()
    body = UpdateProfileRequest(full_name="Track Student", exam_module="academic")
    mock_sb = MagicMock()
    returned = UserPublic(
        id=user_id,
        email="t@example.com",
        full_name="Track Student",
        exam_module="academic",
        role="student",
    )
    with (
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch("app.auth.service.get_user_by_id", new=AsyncMock(return_value=returned)),
    ):
        result = asyncio.run(update_user_profile(user_id=user_id, body=body))

    assert result.user.exam_module == "academic"
    payload = mock_sb.table.return_value.update.call_args[0][0]
    assert payload["exam_module"] == "academic"
    assert "ielts_purpose" not in payload


def test_update_profile_persists_exam_module_general_training():
    user_id = uuid4()
    body = UpdateProfileRequest(
        full_name="GT Student", exam_module="general_training"
    )
    mock_sb = MagicMock()
    returned = UserPublic(
        id=user_id,
        email="gt@example.com",
        full_name="GT Student",
        exam_module="general_training",
        role="student",
    )
    with (
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch("app.auth.service.get_user_by_id", new=AsyncMock(return_value=returned)),
    ):
        result = asyncio.run(update_user_profile(user_id=user_id, body=body))

    assert result.user.exam_module == "general_training"
    payload = mock_sb.table.return_value.update.call_args[0][0]
    assert payload["exam_module"] == "general_training"


def test_update_profile_purpose_does_not_overwrite_exam_module():
    """ielts_purpose-only patch must not write exam_module."""
    user_id = uuid4()
    body = UpdateProfileRequest(
        full_name="Keep Track",
        ielts_purpose="immigration",
    )
    mock_sb = MagicMock()
    returned = UserPublic(
        id=user_id,
        email="k@example.com",
        full_name="Keep Track",
        ielts_purpose="immigration",
        exam_module="academic",  # pre-existing selection
        role="student",
    )
    with (
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch("app.auth.service.get_user_by_id", new=AsyncMock(return_value=returned)),
    ):
        result = asyncio.run(update_user_profile(user_id=user_id, body=body))

    payload = mock_sb.table.return_value.update.call_args[0][0]
    assert payload["ielts_purpose"] == "immigration"
    assert "exam_module" not in payload
    assert result.user.exam_module == "academic"


def test_legacy_null_exam_module_not_silently_written():
    """Profile update without exam_module leaves column untouched (stays NULL)."""
    user_id = uuid4()
    body = UpdateProfileRequest(
        full_name="Legacy",
        ielts_purpose="university",
        target_band=7.0,
    )
    mock_sb = MagicMock()
    returned = UserPublic(
        id=user_id,
        email="legacy@example.com",
        full_name="Legacy",
        ielts_purpose="university",
        exam_module=None,
        role="student",
    )
    with (
        patch("app.auth.service.get_supabase", return_value=mock_sb),
        patch("app.auth.service.get_user_by_id", new=AsyncMock(return_value=returned)),
    ):
        result = asyncio.run(update_user_profile(user_id=user_id, body=body))

    payload = mock_sb.table.return_value.update.call_args[0][0]
    assert "exam_module" not in payload
    assert result.user.exam_module is None
    assert result.user.ielts_purpose == "university"
