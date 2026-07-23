"""Business logic for payments: orders, verification, subscriptions."""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.auth.schemas import UserPublic
from app.auth.utils import is_valid_india_phone, normalize_india_phone, phone_e164
from app.config import get_settings
from app.payments import razorpay_client, repository
from app.payments.constants import (
    PAYMENT_CREATED,
    PAYMENT_PAID,
    PAYMENT_REFUNDED,
    SUBSCRIPTION_ACTIVE,
)
from app.payments.exceptions import (
    PaymentAmountMismatchError,
    PaymentConsistencyError,
    PaymentFetchError,
    PaymentNotCapturedError,
    PaymentNotFoundError,
    PaymentRefundedError,
    PaymentsDisabledError,
    PlanNotFoundError,
    RazorpayAuthError,
    SignatureVerificationError,
)
from app.payments.logging import payment_log
from app.payments.schemas import (
    CheckoutContact,
    CreateOrderResponse,
    OpsStatusResponse,
    PaymentHistoryItem,
    PaymentHistoryResponse,
    PlanOut,
    PlansResponse,
    RazorpayOrderPayload,
    SubscriptionOut,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
)

_CONSISTENCY_RETRY_SEC = 0.15


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def ensure_enabled() -> None:
    if not get_settings().razorpay_enabled:
        raise PaymentsDisabledError()


def ensure_razorpay_ready() -> None:
    ensure_enabled()
    if not razorpay_client.credentials_ready():
        raise RazorpayAuthError()


def get_plans() -> PlansResponse:
    rows = repository.list_active_plans()
    settings = get_settings()
    payments_enabled = razorpay_client.credentials_ready()
    key_id = settings.razorpay_key_id or ""
    return PlansResponse(
        plans=[PlanOut.model_validate(r) for r in rows],
        payments_enabled=payments_enabled,
        checkout_test_mode=payments_enabled and key_id.startswith("rzp_test_"),
    )


def _checkout_contact_for_user(user: UserPublic) -> CheckoutContact:
    """Razorpay card OTP is SMS'd to prefill.contact — E.164 +91… per Razorpay docs."""
    contact: str | None = None
    if user.phone:
        digits = normalize_india_phone(user.phone)
        if is_valid_india_phone(digits):
            contact = phone_e164(digits)
    return CheckoutContact(
        name=user.full_name,
        email=user.email,
        contact=contact,
    )


def _payment_row_is_consistent(
    *,
    row: dict[str, Any] | None,
    row_count: int,
    user: UserPublic,
    plan: dict[str, Any],
    razorpay_order_id: str,
    amount: int,
    currency: str,
) -> dict[str, Any]:
    """Return consistency metadata and whether the row is valid."""
    found = row is not None and bool(row.get("id"))
    status_val = str(row.get("status") or "") if row else ""
    meta = {
        "found": found,
        "status": status_val or None,
        "row_count": row_count,
        "order_matches": bool(
            row and str(row.get("razorpay_order_id") or "") == razorpay_order_id
        ),
        "user_matches": bool(row and str(row.get("user_id") or "") == str(user.id)),
        "plan_matches": bool(row and str(row.get("plan_id") or "") == str(plan["id"])),
        "amount_matches": bool(row and int(row.get("amount") or -1) == int(amount)),
        "currency_matches": bool(
            row and str(row.get("currency") or "") == str(currency)
        ),
        "status_ok": status_val == PAYMENT_CREATED,
    }
    meta["valid"] = (
        row_count == 1
        and meta["found"]
        and meta["status_ok"]
        and meta["order_matches"]
        and meta["user_matches"]
        and meta["plan_matches"]
        and meta["amount_matches"]
        and meta["currency_matches"]
    )
    return meta


def _prove_payment_persisted(
    *,
    user: UserPublic,
    plan: dict[str, Any],
    razorpay_order_id: str,
    amount: int,
    currency: str,
) -> dict[str, Any]:
    """Re-read payments row (one retry if missing). Raise if consistency cannot be proven."""
    last_meta: dict[str, Any] = {}
    for attempt in (1, 2):
        row_count = repository.count_payments_by_order_id(razorpay_order_id)
        row = (
            repository.get_payment_by_order_id(razorpay_order_id)
            if row_count == 1
            else None
        )
        meta = _payment_row_is_consistent(
            row=row,
            row_count=row_count,
            user=user,
            plan=plan,
            razorpay_order_id=razorpay_order_id,
            amount=amount,
            currency=currency,
        )
        last_meta = meta
        payment_log(
            "DB_CONSISTENCY_CHECK",
            attempt=attempt,
            razorpay_order=razorpay_order_id,
            **{k: v for k, v in meta.items() if k != "valid"},
        )
        if meta["valid"] and row is not None:
            payment_log(
                "DB_CONSISTENCY_OK",
                razorpay_order=razorpay_order_id,
                payment_id=str(row["id"]),
                status=PAYMENT_CREATED,
            )
            return row
        if row_count > 1:
            break
        if attempt == 1 and row_count == 0:
            time.sleep(_CONSISTENCY_RETRY_SEC)
            continue
        break

    payment_log(
        "DB_CONSISTENCY_FAIL",
        razorpay_order=razorpay_order_id,
        **{k: v for k, v in last_meta.items() if k != "valid"},
    )
    raise PaymentConsistencyError()


def create_order(*, user: UserPublic, plan_slug: str) -> CreateOrderResponse:
    ensure_razorpay_ready()
    plan = repository.get_plan_by_slug(plan_slug)
    if not plan:
        raise PlanNotFoundError()

    payload = RazorpayOrderPayload(
        amount=int(plan["amount"]),
        currency=str(plan["currency"]),
        receipt=secrets.token_hex(16),
    )
    order = razorpay_client.create_order(payload)
    razorpay_order_id = str(order["id"])

    payment_log(
        "RAZORPAY_ORDER_CREATED",
        razorpay_order=razorpay_order_id,
        amount=payload.amount,
        currency=payload.currency,
    )

    inserted = repository.insert_payment(
        user_id=user.id,
        plan_id=plan["id"],
        razorpay_order_id=razorpay_order_id,
        amount=payload.amount,
        currency=payload.currency,
    )
    payment_log(
        "PAYMENT_INSERTED",
        user_id=str(user.id),
        plan_id=str(plan["id"]),
        payment_id=str(inserted.get("id") or ""),
        razorpay_order=razorpay_order_id,
        amount=payload.amount,
    )

    verified = _prove_payment_persisted(
        user=user,
        plan=plan,
        razorpay_order_id=razorpay_order_id,
        amount=payload.amount,
        currency=payload.currency,
    )

    payment_log(
        "PAYMENT_PERSISTED",
        user_id=str(user.id),
        plan_id=str(plan["id"]),
        payment_id=str(verified["id"]),
        razorpay_order=razorpay_order_id,
        status=PAYMENT_CREATED,
    )
    payment_log(
        "CREATE_ORDER",
        user_id=str(user.id),
        plan_id=str(plan["id"]),
        amount=payload.amount,
        payment_id=str(verified["id"]),
        razorpay_order=razorpay_order_id,
        success=True,
    )

    settings = get_settings()
    config_id = (settings.razorpay_checkout_config_id or "").strip() or None

    return CreateOrderResponse(
        order_id=razorpay_order_id,
        key_id=settings.razorpay_key_id,
        amount=payload.amount,
        currency=payload.currency,
        plan_name=str(plan["name"]),
        checkout_contact=_checkout_contact_for_user(user),
        checkout_config_id=config_id,
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
    captured_amount: int | None = None,
) -> SubscriptionOut:
    """Single path for granting access after payment — used by /verify and webhook."""
    payment = repository.get_payment_by_order_id(razorpay_order_id)
    if not payment:
        payment_log(
            "PAYMENT_LOOKUP",
            order=razorpay_order_id,
            payment=razorpay_payment_id,
            result="NOT_FOUND",
        )
        raise PaymentNotFoundError()
    if user_id is not None and str(payment["user_id"]) != str(user_id):
        payment_log(
            "PAYMENT_LOOKUP",
            order=razorpay_order_id,
            payment=razorpay_payment_id,
            result="NOT_FOUND",
            reason="ownership_mismatch",
        )
        raise PaymentNotFoundError()

    payment_log(
        "PAYMENT_LOOKUP",
        order=razorpay_order_id,
        payment=razorpay_payment_id,
        result="FOUND",
        payment_id=str(payment["id"]),
        user_id=str(payment["user_id"]),
        plan_id=str(payment["plan_id"]) if payment.get("plan_id") else None,
    )

    payment_user_id = UUID(str(payment["user_id"]))

    if payment["status"] == PAYMENT_REFUNDED:
        payment_log(
            "PAYMENT_REFUNDED_BLOCKED",
            user_id=str(payment_user_id),
            payment_id=str(payment["id"]),
            order=razorpay_order_id,
            payment=razorpay_payment_id,
        )
        raise PaymentRefundedError()

    if payment["status"] == PAYMENT_PAID:
        existing_subs = repository.list_subscriptions_for_payment(payment["id"])
        if existing_subs:
            payment_log(
                "SUBSCRIPTION_ALREADY_EXISTS",
                user_id=str(payment_user_id),
                payment_id=str(payment["id"]),
                order=razorpay_order_id,
            )
            return get_subscription(user_id=payment_user_id)
        # Paid but missing subscription — continue into bundle/fallback to repair.

    plan = (
        repository.get_plan_by_id(payment["plan_id"])
        if payment.get("plan_id")
        else None
    )
    if not plan:
        raise PaymentNotFoundError()

    expected_amount = int(payment["amount"])
    if captured_amount is not None and int(captured_amount) != expected_amount:
        payment_log(
            "PAYMENT_AMOUNT_MISMATCH",
            user_id=str(payment_user_id),
            plan_id=str(plan["id"]),
            order=razorpay_order_id,
            payment=razorpay_payment_id,
            success=False,
            expected=expected_amount,
            captured=captured_amount,
        )
        raise PaymentAmountMismatchError()

    starts_at, expires_at = _compute_subscription_dates(payment_user_id, plan)
    repository.confirm_payment_paid_bundle(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
        starts_at=starts_at,
        expires_at=expires_at,
    )

    if plan.get("slug") == "full_skill_program":
        from app.learning.ingest import load_user_exam_and_target
        from app.learning.service import schedule_personalized_plan_generation

        schedule_personalized_plan_generation(payment_user_id)
        user_row = load_user_exam_and_target(payment_user_id)
        if not user_row or not user_row.get("exam_date"):
            payment_log(
                "PLAN_GEN_MISSING_EXAM_DATE",
                user_id=str(payment_user_id),
                order=razorpay_order_id,
            )

    return get_subscription(user_id=payment_user_id)


def verify_payment(
    *, user: UserPublic, body: VerifyPaymentRequest
) -> VerifyPaymentResponse:
    ensure_enabled()
    payment_log(
        "VERIFY_RECEIVED",
        user_id=str(user.id),
        order=body.razorpay_order_id,
        payment=body.razorpay_payment_id,
        signature_present=bool(body.razorpay_signature),
    )
    if not razorpay_client.verify_payment_signature(
        razorpay_order_id=body.razorpay_order_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_signature=body.razorpay_signature,
    ):
        payment_log(
            "SIGNATURE_VALID",
            user_id=str(user.id),
            order=body.razorpay_order_id,
            payment=body.razorpay_payment_id,
            valid=False,
        )
        raise SignatureVerificationError()

    payment_log(
        "SIGNATURE_VALID",
        user_id=str(user.id),
        order=body.razorpay_order_id,
        payment=body.razorpay_payment_id,
        valid=True,
    )

    try:
        rzp_payment = razorpay_client.fetch_payment(body.razorpay_payment_id)
    except RazorpayAuthError:
        raise
    except Exception as exc:
        payment_log(
            "RAZORPAY_FETCH_FAILED",
            user_id=str(user.id),
            order=body.razorpay_order_id,
            payment=body.razorpay_payment_id,
            error=str(exc)[:300],
        )
        raise PaymentFetchError() from exc

    status_raw = str(rzp_payment.get("status") or "").lower()
    captured = rzp_payment.get("captured") is True or status_raw == "captured"
    if not captured:
        payment_log(
            "PAYMENT_NOT_CAPTURED",
            user_id=str(user.id),
            order=body.razorpay_order_id,
            payment=body.razorpay_payment_id,
            status=status_raw,
        )
        raise PaymentNotCapturedError()

    amount_raw = rzp_payment.get("amount")
    if amount_raw is None:
        raise PaymentFetchError()
    captured_amount = int(amount_raw)

    subscription = confirm_payment_paid(
        razorpay_order_id=body.razorpay_order_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_signature=body.razorpay_signature,
        user_id=user.id,
        captured_amount=captured_amount,
    )
    payment_log(
        "VERIFY_SUCCESS",
        user_id=str(user.id),
        order=body.razorpay_order_id,
        payment=body.razorpay_payment_id,
        subscription_active=bool(subscription.is_active),
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
                razorpay_payment_id=row.get("razorpay_payment_id"),
            )
        )
    return PaymentHistoryResponse(payments=items)


def _key_mode(key_id: str) -> str:
    if key_id.startswith("rzp_live_"):
        return "LIVE"
    if key_id.startswith("rzp_test_"):
        return "TEST"
    return "UNKNOWN"


def get_ops_status() -> OpsStatusResponse:
    """Non-secret readiness flags for admin/ops dashboards."""
    settings = get_settings()
    key_id = (settings.razorpay_key_id or "").strip()
    prefix = key_id[:12] if key_id else ""

    cached = razorpay_client.get_cached_credentials_probe()
    if cached is None and settings.razorpay_enabled and key_id and settings.razorpay_key_secret:
        ok, _ = razorpay_client.probe_credentials()
        razorpay_client.set_credentials_probe_result(ok)
        probe_ok = ok
    else:
        probe_ok = bool(cached)

    return OpsStatusResponse(
        razorpay_enabled=bool(settings.razorpay_enabled),
        mode=_key_mode(key_id),
        key_id_prefix=prefix,
        webhook_secret_configured=bool((settings.razorpay_webhook_secret or "").strip()),
        credentials_probe_ok=probe_ok,
        app_env=str(settings.app_env or "development"),
    )
