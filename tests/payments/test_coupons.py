"""Coupon redeem: 100% bypass path (no Razorpay)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.main import app
from app.payments import service
from app.payments.exceptions import (
    CouponExhaustedError,
    CouponInvalidError,
    CouponUserAlreadyRedeemedError,
    GuestCheckoutNotAllowedError,
)
from app.payments.schemas import SubscriptionOut

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
USER_ID_2 = UUID("00000000-0000-4000-8000-0000000000a2")
PLAN_ID = UUID("00000000-0000-4000-8000-0000000000b2")
PAYMENT_ID = UUID("00000000-0000-4000-8000-0000000000c3")
SUB_ID = UUID("00000000-0000-4000-8000-0000000000d4")
COUPON_ID = UUID("00000000-0000-4000-8000-0000000000e5")


def _user(*, role: str = "student", user_id: UUID = USER_ID) -> UserPublic:
    return UserPublic(
        id=user_id,
        email="student@example.com",
        full_name="Test Student",
        phone="9876543210",
        target_band=7.5,
        role=role,
    )


def _plan() -> dict:
    return {
        "id": str(PLAN_ID),
        "slug": "full_skill_program",
        "name": "Full Skill Program",
        "amount": 249900,
        "currency": "INR",
        "duration_days": 365,
    }


def _bundle() -> dict:
    return {
        "ok": True,
        "coupon_id": str(COUPON_ID),
        "redemption_id": "00000000-0000-4000-8000-0000000000f6",
        "payment_id": str(PAYMENT_ID),
        "subscription_id": str(SUB_ID),
        "user_id": str(USER_ID),
        "plan_id": str(PLAN_ID),
        "plan_slug": "full_skill_program",
        "razorpay_order_id": "coupon_ord_abc",
        "razorpay_payment_id": "coupon_pay_xyz",
    }


def _active_sub() -> SubscriptionOut:
    return SubscriptionOut(
        is_active=True,
        plan_slug="full_skill_program",
        plan_name="Full Skill Program",
        status="active",
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def authed_client():
    app.dependency_overrides[get_current_user] = lambda: _user()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_redeem_coupon_requires_auth(client: TestClient):
    res = client.post(
        "/api/payments/redeem-coupon",
        json={"plan_slug": "full_skill_program", "code": "BF-K7M2P9X4QW"},
    )
    assert res.status_code == 401


def test_redeem_coupon_guest_forbidden():
    with pytest.raises(GuestCheckoutNotAllowedError):
        service.redeem_coupon(
            user=_user(role="guest"),
            plan_slug="full_skill_program",
            code="BF-K7M2P9X4QW",
        )


def test_redeem_coupon_happy_path(authed_client: TestClient):
    with (
        patch(
            "app.payments.service.repository.get_plan_by_slug",
            return_value=_plan(),
        ),
        patch(
            "app.payments.service.repository.redeem_coupon_bundle",
            return_value=_bundle(),
        ) as redeem_rpc,
        patch(
            "app.payments.service.repository.invalidate_active_subscription_cache"
        ),
        patch(
            "app.payments.service._apply_fulfillment_side_effects"
        ) as side_effects,
        patch(
            "app.payments.service.get_subscription",
            return_value=_active_sub(),
        ),
        patch(
            "app.security.rate_limit.enforce_redeem_coupon_rate_limit",
        ),
    ):
        res = authed_client.post(
            "/api/payments/redeem-coupon",
            json={"plan_slug": "full_skill_program", "code": " bf-k7m2p9x4qw "},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["subscription"]["is_active"] is True
    assert body["subscription"]["plan_slug"] == "full_skill_program"
    redeem_rpc.assert_called_once()
    assert redeem_rpc.call_args.kwargs["code"] == "BF-K7M2P9X4QW"
    side_effects.assert_called_once()


def test_redeem_coupon_invalid_code(authed_client: TestClient):
    with (
        patch(
            "app.payments.service.repository.get_plan_by_slug",
            return_value=_plan(),
        ),
        patch(
            "app.payments.service.repository.redeem_coupon_bundle",
            side_effect=CouponInvalidError(),
        ),
        patch("app.security.rate_limit.enforce_redeem_coupon_rate_limit"),
    ):
        res = authed_client.post(
            "/api/payments/redeem-coupon",
            json={"plan_slug": "full_skill_program", "code": "NOPE"},
        )
    assert res.status_code == 400
    assert "Invalid coupon" in res.json()["detail"]


def test_redeem_coupon_exhausted(authed_client: TestClient):
    with (
        patch(
            "app.payments.service.repository.get_plan_by_slug",
            return_value=_plan(),
        ),
        patch(
            "app.payments.service.repository.redeem_coupon_bundle",
            side_effect=CouponExhaustedError(),
        ),
        patch("app.security.rate_limit.enforce_redeem_coupon_rate_limit"),
    ):
        res = authed_client.post(
            "/api/payments/redeem-coupon",
            json={"plan_slug": "full_skill_program", "code": "BF-K7M2P9X4QW"},
        )
    assert res.status_code == 400
    assert "already been used" in res.json()["detail"]


def test_redeem_coupon_user_already_redeemed(authed_client: TestClient):
    with (
        patch(
            "app.payments.service.repository.get_plan_by_slug",
            return_value=_plan(),
        ),
        patch(
            "app.payments.service.repository.redeem_coupon_bundle",
            side_effect=CouponUserAlreadyRedeemedError(),
        ),
        patch("app.security.rate_limit.enforce_redeem_coupon_rate_limit"),
    ):
        res = authed_client.post(
            "/api/payments/redeem-coupon",
            json={"plan_slug": "full_skill_program", "code": "BF-N3R8T5W2YZ"},
        )
    assert res.status_code == 400
    assert "already redeemed" in res.json()["detail"]


def test_redeem_coupon_plan_not_found(authed_client: TestClient):
    with (
        patch(
            "app.payments.service.repository.get_plan_by_slug",
            return_value=None,
        ),
        patch("app.security.rate_limit.enforce_redeem_coupon_rate_limit"),
    ):
        res = authed_client.post(
            "/api/payments/redeem-coupon",
            json={"plan_slug": "missing_plan", "code": "BF-K7M2P9X4QW"},
        )
    assert res.status_code == 404


def test_repository_maps_rpc_errors():
    from app.payments import repository

    err = Exception("ERROR: coupon_exhausted")
    fake_client = SimpleNamespace(
        rpc=lambda *a, **k: SimpleNamespace(execute=lambda: (_ for _ in ()).throw(err))
    )
    with (
        patch("app.payments.repository.get_supabase", return_value=fake_client),
        patch("app.payments.repository._exec", side_effect=err),
        pytest.raises(CouponExhaustedError),
    ):
        repository.redeem_coupon_bundle(
            user_id=USER_ID,
            plan_slug="full_skill_program",
            code="BF-K7M2P9X4QW",
        )


def test_service_normalizes_code_and_runs_side_effects():
    with (
        patch(
            "app.payments.service.repository.get_plan_by_slug",
            return_value=_plan(),
        ),
        patch(
            "app.payments.service.repository.redeem_coupon_bundle",
            return_value=_bundle(),
        ) as redeem_rpc,
        patch(
            "app.payments.service.repository.invalidate_active_subscription_cache"
        ),
        patch(
            "app.payments.service._apply_fulfillment_side_effects"
        ) as side_effects,
        patch(
            "app.payments.service.get_subscription",
            return_value=_active_sub(),
        ),
    ):
        out = service.redeem_coupon(
            user=_user(),
            plan_slug="full_skill_program",
            code="bf-k7m2p9x4qw",
        )
    assert out.ok is True
    assert out.subscription.is_active is True
    assert redeem_rpc.call_args.kwargs["code"] == "BF-K7M2P9X4QW"
    assert side_effects.called
