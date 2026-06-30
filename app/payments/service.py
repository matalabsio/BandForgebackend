"""Business logic for payments: orders, verification, subscriptions."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.auth.schemas import UserPublic
from app.config import get_settings
from app.payments import razorpay_client, repository
from app.payments.constants import (
    PAYMENT_PAID,
    SUBSCRIPTION_ACTIVE,
)
from app.payments.exceptions import (
    PaymentNotFoundError,
    PaymentsDisabledError,
    PlanNotFoundError,
    SignatureVerificationError,
)
from app.payments.logging import payment_log
from app.payments.schemas import (
    CheckoutContact,
    CreateOrderResponse,
    PaymentHistoryItem,
    PaymentHistoryResponse,
    PlanOut,
    PlansResponse,
    RazorpayOrderPayload,
    SubscriptionOut,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def ensure_enabled() -> None:
    if not get_settings().razorpay_enabled:
        raise PaymentsDisabledError()


def get_plans() -> PlansResponse:
    rows = repository.list_active_plans()
    return PlansResponse(plans=[PlanOut.model_validate(r) for r in rows])


def create_order(*, user: UserPublic, plan_slug: str) -> CreateOrderResponse:
    ensure_enabled()
    plan = repository.get_plan_by_slug(plan_slug)
    if not plan:
        raise PlanNotFoundError()

    payload = RazorpayOrderPayload(
        amount=int(plan["amount"]),
        currency=str(plan["currency"]),
        receipt=secrets.token_hex(16),
    )
    order = razorpay_client.create_order(payload)

    repository.insert_payment(
        user_id=user.id,
        plan_id=plan["id"],
        razorpay_order_id=str(order["id"]),
        amount=payload.amount,
        currency=payload.currency,
    )

    payment_log(
        "create_order",
        user_id=str(user.id),
        plan_id=str(plan["id"]),
        order_id=str(order["id"]),
        amount=payload.amount,
    )

    return CreateOrderResponse(
        order_id=str(order["id"]),
        key_id=get_settings().razorpay_key_id,
        amount=payload.amount,
        currency=payload.currency,
        plan_name=str(plan["name"]),
        checkout_contact=CheckoutContact(
            name=user.full_name,
            email=user.email,
            contact=user.phone,
        ),
    )


def _compute_subscription_dates(
    user_id: UUID, plan: dict[str, Any]
) -> tuple[datetime, datetime]:
    """Stack new subscription on top of any active one."""
    now = datetime.now(UTC)
    existing = repository.get_active_subscription(user_id)
    starts_at = now
    if existing:
        current_expiry = _parse_dt(existing.get("expires_at"))
        if current_expiry and current_expiry > now:
            starts_at = current_expiry
    expires_at = starts_at + timedelta(days=int(plan["duration_days"]))
    return starts_at, expires_at


def confirm_payment_paid(
    *,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str | None = None,
    user_id: UUID | None = None,
) -> SubscriptionOut:
    """Single path for granting access after payment — used by /verify and webhook."""
    payment = repository.get_payment_by_order_id(razorpay_order_id)
    if not payment:
        raise PaymentNotFoundError()
    if user_id is not None and str(payment["user_id"]) != str(user_id):
        raise PaymentNotFoundError()

    payment_user_id = UUID(str(payment["user_id"]))

    if payment["status"] == PAYMENT_PAID:
        return get_subscription(user_id=payment_user_id)

    plan = (
        repository.get_plan_by_id(payment["plan_id"])
        if payment.get("plan_id")
        else None
    )
    if not plan:
        raise PaymentNotFoundError()

    starts_at, expires_at = _compute_subscription_dates(payment_user_id, plan)
    repository.confirm_payment_paid_bundle(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
        starts_at=starts_at,
        expires_at=expires_at,
    )

    payment_log(
        "confirm_payment_paid",
        order_id=razorpay_order_id,
        payment_id=razorpay_payment_id,
        user_id=str(payment_user_id),
        success=True,
    )

    return get_subscription(user_id=payment_user_id)


def verify_payment(
    *, user: UserPublic, body: VerifyPaymentRequest
) -> VerifyPaymentResponse:
    ensure_enabled()
    if not razorpay_client.verify_payment_signature(
        razorpay_order_id=body.razorpay_order_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_signature=body.razorpay_signature,
    ):
        payment_log(
            "verify",
            order_id=body.razorpay_order_id,
            payment_id=body.razorpay_payment_id,
            success=False,
        )
        raise SignatureVerificationError()

    subscription = confirm_payment_paid(
        razorpay_order_id=body.razorpay_order_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_signature=body.razorpay_signature,
        user_id=user.id,
    )
    payment_log(
        "verify",
        order_id=body.razorpay_order_id,
        payment_id=body.razorpay_payment_id,
        success=True,
    )
    return VerifyPaymentResponse(subscription=subscription)


def get_subscription(*, user_id: UUID) -> SubscriptionOut:
    row = repository.get_active_subscription(user_id)
    if not row:
        return SubscriptionOut(is_active=False)
    plan = row.get("plans") or {}
    return SubscriptionOut(
        is_active=True,
        plan_slug=plan.get("slug"),
        plan_name=plan.get("name"),
        status=str(row.get("status") or SUBSCRIPTION_ACTIVE),
        starts_at=_parse_dt(row.get("starts_at")),
        expires_at=_parse_dt(row.get("expires_at")),
    )


def get_payment_history(*, user_id: UUID) -> PaymentHistoryResponse:
    rows = repository.list_payments_for_user(user_id)
    items: list[PaymentHistoryItem] = []
    for row in rows:
        plan = row.get("plans") or {}
        items.append(
            PaymentHistoryItem(
                id=UUID(str(row["id"])),
                plan_name=plan.get("name"),
                amount=int(row["amount"]),
                currency=str(row["currency"]),
                status=str(row["status"]),
                created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
            )
        )
    return PaymentHistoryResponse(payments=items)
