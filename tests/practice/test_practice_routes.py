"""API route tests for practice hubs."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

from app.auth.schemas import UserPublic
from app.practice.router import get_practice_hub, list_practice_hubs
from app.practice.schemas import PracticeHubOut

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")


def _user() -> UserPublic:
    return UserPublic(
        id=USER_ID,
        email="student@example.com",
        full_name="Test Student",
        phone="9876543210",
        target_band=7.0,
    )


def test_list_hubs_200_with_entitlement():
    hub = PracticeHubOut(
        id="h1",
        slug="writing-b1-s1",
        skill="writing",
        bank_number=1,
        set_number=1,
        title="Writing Set 1.1",
    )
    with patch("app.practice.router.service.list_hubs_with_progress", return_value=[hub]):
        result = list_practice_hubs(skill="writing", user=_user())  # type: ignore[arg-type]
        assert len(result) == 1
        assert result[0].skill == "writing"


def test_get_hub_detail():
    from app.practice.schemas import PracticeHubDetailOut

    detail = PracticeHubDetailOut(
        id="h1",
        slug="writing-b1-s1",
        skill="writing",
        bank_number=1,
        set_number=1,
        title="Writing Set 1.1",
        practice_prompt="Write an essay.",
    )
    with patch("app.practice.router.service.get_hub_detail", return_value=detail):
        out = get_practice_hub(hub_id="h1", user=_user())  # type: ignore[arg-type]
        assert out.id == "h1"
        assert out.practice_prompt == "Write an essay."
