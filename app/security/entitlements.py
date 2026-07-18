"""Subscription entitlements — the single source of truth for premium access.

Access is derived only from the Supabase ``subscriptions`` table
(``status = 'active' AND expires_at > now()``), never from Razorpay state.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.mock_catalog.constants import M01_MOCK_TEST_ID, M02_MOCK_TEST_ID
from app.payments import repository
from app.payments.schemas import SubscriptionOut
from app.payments.service import get_subscription


def has_active_subscription(user_id: UUID) -> bool:
    return repository.get_active_subscription(user_id) is not None


def has_full_skill_program(user_id: UUID) -> bool:
    sub = repository.get_active_subscription(user_id)
    if not sub:
        return False
    plans = sub.get("plans")
    if isinstance(plans, dict):
        return plans.get("slug") == "full_skill_program"
    return False


async def require_full_skill_program(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> UserPublic:
    """Dependency that gates practice hub routes behind Full Skill Program."""
    if not has_full_skill_program(current_user.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Full Skill Program is required to access practice hubs.",
        )
    return current_user


def get_subscription_status(user_id: UUID) -> SubscriptionOut:
    return get_subscription(user_id=user_id)


async def require_active_subscription(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> UserPublic:
    """Dependency that gates premium-only routes behind an active subscription."""
    if not has_active_subscription(current_user.id):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail="An active subscription is required to access this resource.",
        )
    return current_user


def assert_skill_mock_access(*, user_id: UUID, skill: str) -> None:
    """Raise 403 if the skill full mock is not unlocked via hub progress."""
    from app.practice.service import assert_skill_mock_access as _assert

    _assert(user_id=user_id, skill=skill)


def assert_premium_mock_access(*, user: UserPublic, mock_test_id: UUID) -> None:
    """M01 is free; M02+ requires an active subscription."""
    mock_id = str(mock_test_id)
    if mock_id in (M01_MOCK_TEST_ID,):
        return
    if mock_id == M02_MOCK_TEST_ID and not has_active_subscription(user.id):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail="An active subscription is required to access this mock test.",
        )
