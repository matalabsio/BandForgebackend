"""Subscription entitlements — the single source of truth for premium access.

Access is derived only from the Supabase ``subscriptions`` table
(``status = 'active' AND expires_at > now()``), never from Razorpay state.

Multi-SKU: ``resolve_entitlements`` inspects **all** active subscriptions.
``get_active_subscription`` (latest expiry only) must not be used for skill
gates when a user may hold more than one plan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, TypedDict
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.diagnostic.constants import DIAGNOSTIC_MOCK_TEST_ID

if TYPE_CHECKING:
    from app.payments.schemas import SubscriptionOut

SKILLS = ("listening", "reading", "writing", "speaking")

FULL_SKILL_PROGRAM_SLUG = "full_skill_program"
WRITING_SKILL_SLUG = "writing_skill"
SPEAKING_SKILL_SLUG = "speaking_skill"

# Canonical plan slug → skills granted. Pack SKUs are recognized here so the
# resolver is ready before plans rows are activated; unknown slugs grant nothing.
PLAN_SKILL_GRANTS: dict[str, frozenset[str]] = {
    FULL_SKILL_PROGRAM_SLUG: frozenset(SKILLS),
    WRITING_SKILL_SLUG: frozenset({"writing"}),
    SPEAKING_SKILL_SLUG: frozenset({"speaking"}),
    "dual_bundle": frozenset({"writing", "speaking"}),
    "all_skills_bundle": frozenset(SKILLS),
}


class SkillEntitlements(TypedDict):
    listening: bool
    reading: bool
    writing: bool
    speaking: bool


class Entitlements(TypedDict):
    plans: list[str]
    skills: SkillEntitlements
    writing_skill: bool
    speaking_skill: bool
    full_skill_program: bool


def _empty_skills() -> SkillEntitlements:
    return {
        "listening": False,
        "reading": False,
        "writing": False,
        "speaking": False,
    }


def _plan_slug_from_subscription(row: dict[str, Any]) -> str | None:
    plans = row.get("plans")
    if isinstance(plans, dict):
        slug = plans.get("slug")
        if slug:
            return str(slug)
    return None


def resolve_entitlements(user_id: UUID) -> Entitlements:
    """Union entitlements across all active, non-expired subscriptions.

    Expiry is enforced by the active-subscription query (``expires_at > now()``).
    """
    from app.payments import repository

    rows = repository.list_active_subscriptions(user_id)
    plan_slugs: list[str] = []
    seen: set[str] = set()
    skills = _empty_skills()

    for row in rows:
        slug = _plan_slug_from_subscription(row)
        if not slug:
            continue
        if slug not in seen:
            seen.add(slug)
            plan_slugs.append(slug)
        for skill in PLAN_SKILL_GRANTS.get(slug, ()):
            if skill in skills:
                skills[skill] = True  # type: ignore[literal-required]

    return {
        "plans": plan_slugs,
        "skills": skills,
        "writing_skill": WRITING_SKILL_SLUG in seen,
        "speaking_skill": SPEAKING_SKILL_SLUG in seen,
        "full_skill_program": FULL_SKILL_PROGRAM_SLUG in seen,
    }


def has_active_subscription(user_id: UUID) -> bool:
    from app.payments import repository

    return repository.get_active_subscription(user_id) is not None


def has_full_skill_program(user_id: UUID) -> bool:
    """True when an active subscription includes the Full Skill Program SKU."""
    return resolve_entitlements(user_id)["full_skill_program"]


def has_writing_skill(user_id: UUID) -> bool:
    """True when any active entitlement grants the writing skill.

    FSP and ``writing_skill`` (and future dual/all-skills packs) qualify.
    Unrelated plans (e.g. legacy premium_monthly) do not.
    """
    return resolve_entitlements(user_id)["skills"]["writing"]


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
    from app.payments.service import get_subscription

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
    """Allow free/diagnostic mocks; paid mocks require an active subscription.

    Falls back to Diagnostic UUID allow-list if the row is missing flags during
    migration; unknown non-diagnostic mocks deny by default (404 / 402).
    """
    from app.security.mock_access import get_mock_access_flags

    if mock_test_id == DIAGNOSTIC_MOCK_TEST_ID:
        return

    flags = get_mock_access_flags(mock_test_id)
    enforce_premium_mock_flags(user=user, mock_test_id=mock_test_id, flags=flags)


def enforce_premium_mock_flags(
    *,
    user: UserPublic,
    mock_test_id: UUID,
    flags: dict[str, Any] | None,
    subscription_active: bool | None = None,
) -> None:
    """Apply premium gate using pre-fetched ``mock_tests`` flags (same errors as assert).

    Pass ``subscription_active`` when already known (e.g. gate-context RPC) to
    skip a separate subscriptions lookup.

    Writing / Speaking Skill packs (without FSP) cannot use generic premium
    subscription access; only the allotted pack mock may pass this gate.
    """
    if mock_test_id == DIAGNOSTIC_MOCK_TEST_ID:
        return
    if flags is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Mock test not found.",
        )
    if flags.get("is_free") or flags.get("is_diagnostic"):
        return

    ent = resolve_entitlements(user.id)
    if ent["full_skill_program"]:
        subscribed = (
            subscription_active
            if subscription_active is not None
            else has_active_subscription(user.id)
        )
        if not subscribed:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                detail="An active subscription is required to access this mock test.",
            )
        return

    if ent["writing_skill"]:
        # Pack-only: same rules as writing/mock-attempts (course + allotment + quota).
        # Do not allow L/R/S/module starts to bypass via allotment-only checks.
        from app.practice.writing_skill_mock import assert_writing_skill_mock_for_test

        assert_writing_skill_mock_for_test(
            user_id=user.id, mock_test_id=mock_test_id
        )
        return

    if ent["speaking_skill"]:
        from app.practice.speaking_skill_mock import assert_speaking_skill_mock_for_test

        assert_speaking_skill_mock_for_test(
            user_id=user.id, mock_test_id=mock_test_id
        )
        return

    subscribed = (
        subscription_active
        if subscription_active is not None
        else has_active_subscription(user.id)
    )
    if not subscribed:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail="An active subscription is required to access this mock test.",
        )
