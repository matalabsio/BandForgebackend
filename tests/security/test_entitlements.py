"""Multi-SKU entitlement resolver tests (Phase 1 foundation)."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

from app.security.entitlements import (
    has_full_skill_program,
    has_writing_skill,
    resolve_entitlements,
)

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")


def _sub(slug: str) -> dict:
    return {"plans": {"slug": slug, "name": slug.replace("_", " ").title()}}


def test_resolve_entitlements_no_subscriptions():
    with patch(
        "app.payments.repository.list_active_subscriptions", return_value=[]
    ):
        ent = resolve_entitlements(USER_ID)
        assert ent["plans"] == []
        assert ent["skills"] == {
            "listening": False,
            "reading": False,
            "writing": False,
            "speaking": False,
        }
        assert ent["writing_skill"] is False
        assert ent["full_skill_program"] is False
        assert has_full_skill_program(USER_ID) is False
        assert has_writing_skill(USER_ID) is False


def test_resolve_entitlements_fsp_only():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[_sub("full_skill_program")],
    ):
        ent = resolve_entitlements(USER_ID)
        assert ent["plans"] == ["full_skill_program"]
        assert ent["full_skill_program"] is True
        assert ent["writing_skill"] is False
        assert ent["skills"]["writing"] is True
        assert ent["skills"]["listening"] is True
        assert ent["skills"]["reading"] is True
        assert ent["skills"]["speaking"] is True
        assert has_full_skill_program(USER_ID) is True
        assert has_writing_skill(USER_ID) is True


def test_resolve_entitlements_writing_skill_only():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[_sub("writing_skill")],
    ):
        ent = resolve_entitlements(USER_ID)
        assert ent["plans"] == ["writing_skill"]
        assert ent["writing_skill"] is True
        assert ent["full_skill_program"] is False
        assert ent["skills"]["writing"] is True
        assert ent["skills"]["listening"] is False
        assert ent["skills"]["reading"] is False
        assert ent["skills"]["speaking"] is False
        assert has_full_skill_program(USER_ID) is False
        assert has_writing_skill(USER_ID) is True


def test_resolve_entitlements_fsp_and_writing_skill_simultaneously():
    """Regression: single-row get_active_subscription must not drop a second SKU."""
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[
            _sub("full_skill_program"),
            _sub("writing_skill"),
        ],
    ):
        ent = resolve_entitlements(USER_ID)
        assert set(ent["plans"]) == {"full_skill_program", "writing_skill"}
        assert ent["full_skill_program"] is True
        assert ent["writing_skill"] is True
        assert ent["skills"]["writing"] is True
        assert has_full_skill_program(USER_ID) is True
        assert has_writing_skill(USER_ID) is True


def test_resolve_entitlements_unrelated_subscription_only():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[_sub("premium_monthly")],
    ):
        ent = resolve_entitlements(USER_ID)
        assert ent["plans"] == ["premium_monthly"]
        assert ent["full_skill_program"] is False
        assert ent["writing_skill"] is False
        assert ent["skills"]["writing"] is False
        assert has_full_skill_program(USER_ID) is False
        assert has_writing_skill(USER_ID) is False


def test_resolve_entitlements_expired_writing_skill_excluded():
    """Expiry is enforced by list_active_subscriptions; expired rows never reach resolver."""
    with patch(
        "app.payments.repository.list_active_subscriptions", return_value=[]
    ):
        assert resolve_entitlements(USER_ID)["writing_skill"] is False
        assert has_writing_skill(USER_ID) is False


def test_resolve_entitlements_expired_fsp_excluded():
    with patch(
        "app.payments.repository.list_active_subscriptions", return_value=[]
    ):
        assert resolve_entitlements(USER_ID)["full_skill_program"] is False
        assert has_full_skill_program(USER_ID) is False


def test_resolve_entitlements_multiple_active_subscriptions():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[
            _sub("writing_skill"),
            _sub("premium_monthly"),
            _sub("full_skill_program"),
        ],
    ):
        ent = resolve_entitlements(USER_ID)
        assert set(ent["plans"]) == {
            "writing_skill",
            "premium_monthly",
            "full_skill_program",
        }
        assert ent["full_skill_program"] is True
        assert ent["writing_skill"] is True
        assert all(
            ent["skills"][s] for s in ("listening", "reading", "writing", "speaking")
        )


def test_has_writing_skill_not_implied_by_any_active_subscription():
    with patch(
        "app.payments.repository.list_active_subscriptions",
        return_value=[_sub("starter_monthly")],
    ):
        assert has_writing_skill(USER_ID) is False


def test_list_active_subscriptions_feeds_resolver_not_single_row():
    """FSP still detected when it is not the sole / latest-expiry subscription."""
    rows = [
        _sub("writing_skill"),
        _sub("full_skill_program"),
    ]
    with patch(
        "app.payments.repository.list_active_subscriptions", return_value=rows
    ):
        assert has_full_skill_program(USER_ID) is True
        assert has_writing_skill(USER_ID) is True
        ent = resolve_entitlements(USER_ID)
        assert ent["full_skill_program"] is True
        assert ent["writing_skill"] is True


def test_get_subscription_attaches_multi_sku_entitlements_independent_of_primary_row():
    """Subscription display row may be writing_skill; entitlements still include FSP."""
    from app.payments import service

    primary = {
        "id": "sub-ws",
        "status": "active",
        "starts_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-07-01T00:00:00+00:00",
        "plans": {"slug": "writing_skill", "name": "Writing Skill"},
    }
    with (
        patch(
            "app.security.entitlements.resolve_entitlements",
            return_value={
                "plans": ["full_skill_program", "writing_skill"],
                "skills": {
                    "listening": True,
                    "reading": True,
                    "writing": True,
                    "speaking": True,
                },
                "writing_skill": True,
                "full_skill_program": True,
            },
        ),
        patch(
            "app.payments.service.repository.get_active_subscription",
            return_value=primary,
        ),
    ):
        out = service.get_subscription(user_id=USER_ID)
    assert out.plan_slug == "writing_skill"
    assert out.entitlements.full_skill_program is True
    assert out.entitlements.writing_skill is True
    assert out.entitlements.skills["writing"] is True
