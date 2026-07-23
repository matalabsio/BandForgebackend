"""Razorpay webhook processing.

The webhook is the authoritative, server-to-server confirmation of payment
state. It is idempotent via ``payment_events.razorpay_event_id`` and only acts
after the raw-body signature is verified.

Failed/pending events are reprocessed on Razorpay retry. Transient fulfillment
errors return 503 so the provider retries; permanent business errors do not.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.payments import razorpay_client, repository, service
from app.payments.constants import (
    EVENT_FAILED,
    EVENT_PAYMENT_CAPTURED,
    EVENT_PAYMENT_FAILED,
    EVENT_PENDING,
    EVENT_PROCESSED,
    EVENT_REFUND_CREATED,
    PAYMENT_FAILED,
    PAYMENT_PAID,
    PAYMENT_REFUNDED,
)
from app.payments.exceptions import (
    PaymentAmountMismatchError,
    PaymentNotFoundError,
    PlanNotFoundError,
    WebhookEventIdRequiredError,
    WebhookTransientError,
    WebhookVerificationError,
)
from app.payments.logging import payment_log


def _payment_entity(payload: dict[str, Any]) -> dict[str, Any]:
    return (
        payload.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    ) or {}


def _refund_entity(payload: dict[str, Any]) -> dict[str, Any]:
    return (
        payload.get("payload", {})
        .get("refund", {})
        .get("entity", {})
    ) or {}


def _sanitize_headers(headers: dict[str, str] | None) -> dict[str, Any]:
    if not headers:
        return {}
    out: dict[str, Any] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower == "x-razorpay-signature":
            out[key] = "[present]" if value else "[missing]"
        else:
            out[key] = value
    return out


def _is_permanent_fulfillment_error(exc: Exception) -> bool:
    # PaymentNotFound is transient — order row may lag behind Razorpay capture.
    if isinstance(exc, PaymentNotFoundError):
        return False
    if isinstance(exc, (PaymentAmountMismatchError, PlanNotFoundError)):
        return True
    if isinstance(exc, HTTPException) and exc.status_code in (400, 404):
        # Exclude PaymentNotFoundError (already handled); other 404s stay permanent.
        return not isinstance(exc, PaymentNotFoundError)
    return False


def handle_webhook(
    *,
    raw_body: bytes,
    signature: str,
    event_id: str | None,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not razorpay_client.verify_webhook_signature(
        raw_body=raw_body, signature=signature
    ):
        raise WebhookVerificationError()

    if not (event_id and str(event_id).strip()):
        raise WebhookEventIdRequiredError()
    event_id = str(event_id).strip()

    event_type = str(payload.get("event") or "")
    entity = _payment_entity(payload)
    order_id = entity.get("order_id")
    razorpay_payment_id = entity.get("id")
    captured_amount = entity.get("amount")
    if captured_amount is not None:
        captured_amount = int(captured_amount)

    event_row = repository.insert_payment_event(
        razorpay_event_id=event_id,
        event_type=event_type,
        razorpay_order_id=order_id,
        razorpay_payment_id=razorpay_payment_id,
        payload=payload,
        headers=_sanitize_headers(headers),
    )
    reprocess = False
    if event_row is None:
        existing = repository.get_payment_event_by_razorpay_event_id(event_id)
        if existing and str(existing.get("processing_status") or "") == EVENT_PROCESSED:
            payment_log(
                "webhook",
                user_id=None,
                plan_id=None,
                order_id=order_id,
                payment_id=razorpay_payment_id,
                success=True,
                event_id=event_id,
                event_type=event_type,
                duplicate=True,
                processed=True,
            )
            return {"ok": True, "duplicate": True}
        if not existing:
            raise WebhookTransientError(
                detail="Webhook event conflict; retry shortly."
            )
        status_val = str(existing.get("processing_status") or "")
        if status_val in (EVENT_FAILED, EVENT_PENDING):
            event_row = repository.claim_payment_event_for_retry(existing["id"])
            reprocess = True
            payment_log(
                "webhook",
                user_id=None,
                plan_id=None,
                order_id=order_id,
                payment_id=razorpay_payment_id,
                success=True,
                event_id=event_id,
                event_type=event_type,
                duplicate=True,
                reprocess=True,
                retry_count=event_row.get("retry_count"),
            )
        else:
            return {"ok": True, "duplicate": True}

    event_db_id = event_row.get("id")
    try:
        if event_type == EVENT_PAYMENT_CAPTURED and order_id and razorpay_payment_id:
            service.confirm_payment_paid(
                razorpay_order_id=order_id,
                razorpay_payment_id=razorpay_payment_id,
                captured_amount=captured_amount,
            )
        elif event_type == EVENT_PAYMENT_FAILED and order_id:
            _on_payment_failed(order_id=order_id)
        elif event_type == EVENT_REFUND_CREATED:
            refund = _refund_entity(payload)
            refund_amount = refund.get("amount")
            if refund_amount is not None:
                refund_amount = int(refund_amount)
            _on_refund(
                razorpay_payment_id=refund.get("payment_id"),
                refund_amount=refund_amount,
            )

        if event_db_id:
            repository.mark_event_processed(event_db_id)

        payment_log(
            "webhook",
            user_id=None,
            plan_id=None,
            order_id=order_id,
            payment_id=razorpay_payment_id,
            success=True,
            event_id=event_id,
            event_type=event_type,
            processed=True,
            duplicate=reprocess,
            reprocess=reprocess,
        )
    except Exception as exc:
        if event_db_id:
            repository.mark_event_failed(event_db_id, error=str(exc))
        payment_log(
            "webhook",
            user_id=None,
            plan_id=None,
            order_id=order_id,
            payment_id=razorpay_payment_id,
            success=False,
            event_id=event_id,
            event_type=event_type,
            processed=False,
            error=str(exc),
            reprocess=reprocess,
        )
        if _is_permanent_fulfillment_error(exc):
            return {"ok": True, "processing_failed": True}
        detail = str(exc).strip()[:200] or "Webhook fulfillment temporarily unavailable."
        raise WebhookTransientError(detail=detail) from exc

    return {"ok": True, "reprocess": reprocess} if reprocess else {"ok": True}


def _on_payment_failed(*, order_id: str) -> None:
    payment = repository.get_payment_by_order_id(order_id)
    if not payment or payment["status"] in (PAYMENT_PAID, PAYMENT_REFUNDED):
        return
    repository.mark_payment_status(payment_id=payment["id"], status=PAYMENT_FAILED)


def _on_refund(
    *,
    razorpay_payment_id: str | None,
    refund_amount: int | None = None,
) -> None:
    if not razorpay_payment_id:
        return
    sb_payment = repository.get_payment_by_razorpay_payment_id(razorpay_payment_id)
    if not sb_payment:
        return
    payment_amount = int(sb_payment.get("amount") or 0)
    if refund_amount is not None and refund_amount < payment_amount:
        payment_log(
            "PARTIAL_REFUND_IGNORED",
            user_id=str(sb_payment.get("user_id") or ""),
            payment_id=str(sb_payment["id"]),
            order=str(sb_payment.get("razorpay_order_id") or ""),
            refund_amount=refund_amount,
            payment_amount=payment_amount,
        )
        return
    repository.mark_payment_status(
        payment_id=sb_payment["id"], status=PAYMENT_REFUNDED
    )
    repository.cancel_subscription_for_payment(payment_id=sb_payment["id"])
