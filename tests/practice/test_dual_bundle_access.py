"""Dual Bundle entitlements, practice access, course PCI, independent mocks."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.payments.constants import (
    DUAL_BUNDLE_SLUG,
    PROGRAM_SKILL_SPEAKING,
    PROGRAM_SKILL_WRITING,
    SPEAKING_SKILL_SLUG,
    WRITING_SKILL_SLUG,
)
from app.practice.access import resolve_practice_skill_access
from app.practice.speaking_skill_course import get_speaking_skill_course_context
from app.practice.writing_skill_course import get_writing_skill_course_context
from app.security.entitlements import resolve_entitlements

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
DUAL_SUB = "sub-dual"
WRITING_PLAN = "plan-writing"
SPEAKING_PLAN = "plan-speaking"


def _sub(slug: str, *, plan_id: str | None = None, sub_id: str | None = None) -> dict:
    return {
        "id": sub_id or f"sub-{slug}",
        "plan_id": plan_id or f"plan-{slug}",
        "plans": {"slug": slug, "name": slug.replace("_", " ").title()},
    }


def test_resolve_entitlements_dual_grants_writing_and_speaking_flags():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[_sub(DUAL_BUNDLE_SLUG)],
    ):
        ent = resolve_entitlements(USER_ID)
    assert DUAL_BUNDLE_SLUG in ent["plans"]
    assert ent["writing_skill"] is True
    assert ent["speaking_skill"] is True
    assert ent["full_skill_program"] is False
    assert ent["skills"]["writing"] is True
    assert ent["skills"]["speaking"] is True
    assert ent["skills"]["listening"] is False
    assert ent["skills"]["reading"] is False


def test_resolve_entitlements_writing_only_unchanged():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[_sub(WRITING_SKILL_SLUG)],
    ):
        ent = resolve_entitlements(USER_ID)
    assert ent["writing_skill"] is True
    assert ent["speaking_skill"] is False
    assert ent["skills"]["speaking"] is False


def test_resolve_entitlements_speaking_only_unchanged():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[_sub(SPEAKING_SKILL_SLUG)],
    ):
        ent = resolve_entitlements(USER_ID)
    assert ent["speaking_skill"] is True
    assert ent["writing_skill"] is False
    assert ent["skills"]["writing"] is False


def test_practice_access_dual_resolves_to_pack_modes():
    dual_ent = {
        "plans": [DUAL_BUNDLE_SLUG],
        "skills": {
            "listening": False,
            "reading": False,
            "writing": True,
            "speaking": True,
        },
        "writing_skill": True,
        "speaking_skill": True,
        "full_skill_program": False,
    }
    with patch("app.practice.access.resolve_entitlements", return_value=dual_ent):
        assert (
            resolve_practice_skill_access(user_id=USER_ID, skill="writing")
            == "writing_skill"
        )
        assert (
            resolve_practice_skill_access(user_id=USER_ID, skill="speaking")
            == "speaking_skill"
        )
        with pytest.raises(HTTPException) as exc:
            resolve_practice_skill_access(user_id=USER_ID, skill="listening")
        assert exc.value.status_code == 403


def test_practice_access_expired_dual_denied():
    empty = {
        "plans": [],
        "skills": {
            "listening": False,
            "reading": False,
            "writing": False,
            "speaking": False,
        },
        "writing_skill": False,
        "speaking_skill": False,
        "full_skill_program": False,
    }
    with patch("app.practice.access.resolve_entitlements", return_value=empty):
        with pytest.raises(HTTPException) as exc:
            resolve_practice_skill_access(user_id=USER_ID, skill="writing")
        assert exc.value.status_code == 403


def test_writing_course_context_dual_uses_writing_skill_plan_id():
    dual_sub = _sub(
        DUAL_BUNDLE_SLUG, plan_id="plan-dual", sub_id=DUAL_SUB
    )
    usage = {
        "id": "usage-w",
        "skill": PROGRAM_SKILL_WRITING,
        "plan_id": WRITING_PLAN,
        "exam_module": "academic",
        "mocks_granted": 1,
        "mocks_used": 0,
    }
    with (
        patch(
            "app.payments.repository.list_active_subscriptions",
            return_value=[dual_sub],
        ),
        patch(
            "app.payments.repository.get_plan_row_by_slug",
            return_value={"id": WRITING_PLAN, "slug": WRITING_SKILL_SLUG},
        ),
        patch(
            "app.payments.repository.get_user_program_usage_by_subscription",
            return_value=usage,
        ) as get_usage,
    ):
        ctx = get_writing_skill_course_context(USER_ID)

    assert ctx["subscription_id"] == DUAL_SUB
    assert ctx["plan_id"] == WRITING_PLAN
    assert ctx["exam_module"] == "academic"
    get_usage.assert_called_once_with(DUAL_SUB, skill=PROGRAM_SKILL_WRITING)


def test_speaking_course_context_dual_uses_speaking_skill_plan_id():
    dual_sub = _sub(
        DUAL_BUNDLE_SLUG, plan_id="plan-dual", sub_id=DUAL_SUB
    )
    usage = {
        "id": "usage-s",
        "skill": PROGRAM_SKILL_SPEAKING,
        "plan_id": SPEAKING_PLAN,
        "mocks_granted": 1,
        "mocks_used": 0,
    }
    with (
        patch(
            "app.payments.repository.list_active_subscriptions",
            return_value=[dual_sub],
        ),
        patch(
            "app.payments.repository.get_plan_row_by_slug",
            return_value={"id": SPEAKING_PLAN, "slug": SPEAKING_SKILL_SLUG},
        ),
        patch(
            "app.payments.repository.get_user_program_usage_by_subscription",
            return_value=usage,
        ) as get_usage,
    ):
        ctx = get_speaking_skill_course_context(USER_ID)

    assert ctx["subscription_id"] == DUAL_SUB
    assert ctx["plan_id"] == SPEAKING_PLAN
    get_usage.assert_called_once_with(DUAL_SUB, skill=PROGRAM_SKILL_SPEAKING)


def test_writing_course_context_prefers_writing_skill_over_dual():
    writing_sub = _sub(
        WRITING_SKILL_SLUG, plan_id=WRITING_PLAN, sub_id="sub-w"
    )
    dual_sub = _sub(DUAL_BUNDLE_SLUG, plan_id="plan-dual", sub_id=DUAL_SUB)
    usage = {"id": "usage-w", "exam_module": "general_training"}
    with (
        patch(
            "app.payments.repository.list_active_subscriptions",
            return_value=[dual_sub, writing_sub],
        ),
        patch(
            "app.payments.repository.get_user_program_usage_by_subscription",
            return_value=usage,
        ) as get_usage,
        patch("app.payments.repository.get_plan_row_by_slug") as sibling,
    ):
        ctx = get_writing_skill_course_context(USER_ID)

    assert ctx["subscription_id"] == "sub-w"
    assert ctx["plan_id"] == WRITING_PLAN
    get_usage.assert_called_once_with("sub-w", skill=PROGRAM_SKILL_WRITING)
    sibling.assert_not_called()


def test_dual_mock_quotas_are_independent():
    """Consuming writing usage must not touch speaking usage (usage_id scoped)."""
    from app.practice.speaking_skill_mock import consume_speaking_skill_mock_quota
    from app.practice.writing_skill_mock import consume_writing_skill_mock_quota

    writing_usage = {
        "id": "usage-w",
        "skill": PROGRAM_SKILL_WRITING,
        "mocks_granted": 1,
        "mocks_used": 1,
    }
    speaking_usage = {
        "id": "usage-s",
        "skill": PROGRAM_SKILL_SPEAKING,
        "mocks_granted": 1,
        "mocks_used": 0,
    }

    with patch(
        "app.payments.repository.consume_user_program_mock_quota_atomic",
        return_value=writing_usage,
    ) as consume:
        out = consume_writing_skill_mock_quota(usage_id="usage-w")
    assert out["mocks_used"] == 1
    consume.assert_called_once_with(usage_id="usage-w")

    with patch(
        "app.payments.repository.consume_user_program_mock_quota_atomic",
        return_value={**speaking_usage, "mocks_used": 1},
    ) as consume_s:
        out_s = consume_speaking_skill_mock_quota(usage_id="usage-s")
    assert out_s["mocks_used"] == 1
    consume_s.assert_called_once_with(usage_id="usage-s")
