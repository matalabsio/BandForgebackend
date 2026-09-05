"""FastAPI routes for the payments module."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.admin.dependencies import require_admin
from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.payments import service, webhook
from app.payments.schemas import (
    CreateOrderRequest,
    CreateOrderResponse,
    OpsStatusResponse,
    PaymentHistoryResponse,
    PlansResponse,
    RedeemCouponRequest,
    RedeemCouponResponse,
    SubscriptionOut,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
    WebhookResponse,
)
from app.security.rate_limit import (
    enforce_create_order_rate_limit,
    enforce_redeem_coupon_rate_limit,
    enforce_verify_rate_limit,
)

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.get("/plans", response_model=PlansResponse)
def list_plans() -> PlansResponse:
    return service.get_plans()


@router.post("/create-order", response_model=CreateOrderResponse)
def create_order(
    body: CreateOrderRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> CreateOrderResponse:
    enforce_create_order_rate_limit(user_id=str(current_user.id))
    return service.create_order(user=current_user, plan_slug=body.plan_slug)


@router.post("/verify", response_model=VerifyPaymentResponse)
def verify_payment(
    body: VerifyPaymentRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> VerifyPaymentResponse:
    enforce_verify_rate_limit(user_id=str(current_user.id))
    return service.verify_payment(user=current_user, body=body)


@router.post("/redeem-coupon", response_model=RedeemCouponResponse)
def redeem_coupon(
    body: RedeemCouponRequest,
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> RedeemCouponResponse:
    enforce_redeem_coupon_rate_limit(user_id=str(current_user.id))
    return service.redeem_coupon(
        user=current_user,
        plan_slug=body.plan_slug,
        code=body.code,
    )


@router.get("/subscription", response_model=SubscriptionOut)
def get_subscription(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> SubscriptionOut:
    return service.get_subscription(user_id=current_user.id)


@router.get("/history", response_model=PaymentHistoryResponse)
def payment_history(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> PaymentHistoryResponse:
    return service.get_payment_history(user_id=current_user.id)


@router.get("/ops-status", response_model=OpsStatusResponse)
def ops_status(
    _admin: Annotated[UserPublic, Depends(require_admin)],
) -> OpsStatusResponse:
    return service.get_ops_status()


@router.post("/webhook", response_model=WebhookResponse)
async def razorpay_webhook(request: Request) -> WebhookResponse:
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        payload = {}
    event_id = request.headers.get("X-Razorpay-Event-Id") or payload.get("id")
    result = webhook.handle_webhook(
        raw_body=raw_body,
        signature=signature,
        event_id=event_id,
        payload=payload,
        headers=dict(request.headers),
    )
    return WebhookResponse(ok=bool(result.get("ok", True)))
