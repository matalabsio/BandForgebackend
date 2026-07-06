"""Razorpay webhook processing.

The webhook is the authoritative, server-to-server confirmation of payment
state. It is idempotent via ``payment_events.razorpay_event_id`` and only acts
after the raw-body signature is verified.
"""

from __future__ import annotations

from typing import Any

from app.payments import razorpay_client, repository, service
from app.payments.constants import (
    EVENT_PAYMENT_CAPTURED,
    EVENT_PAYMENT_FAILED,
    EVENT_REFUND_CREATED,
    PAYMENT_FAILED,
    PAYMENT_PAID,
    PAYMENT_REFUNDED,
)
from app.payments.exceptions import WebhookVerificationError
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
    if event_row is None:
        payment_log(
            "webhook",
            event_id=event_id,
            event_type=event_type,
            duplicate=True,
            processed=False,
        )
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
            _on_refund(razorpay_payment_id=refund.get("payment_id"))

        if event_db_id:
            repository.mark_event_processed(event_db_id)

        payment_log(
            "webhook",
            event_id=event_id,
            event_type=event_type,
            processed=True,
            duplicate=False,
        )
    except Exception as exc:
        if event_db_id:
            repository.mark_event_failed(event_db_id, error=str(exc))
        payment_log(
            "webhook",
            event_id=event_id,
            event_type=event_type,
            processed=False,
            error=str(exc),
        )
        return {"ok": True, "processing_failed": True}

    return {"ok": True}


def _on_payment_failed(*, order_id: str) -> None:
    payment = repository.get_payment_by_order_id(order_id)
    if not payment or payment["status"] in (PAYMENT_PAID, PAYMENT_REFUNDED):
        return
    repository.mark_payment_status(payment_id=payment["id"], status=PAYMENT_FAILED)


def _on_refund(*, razorpay_payment_id: str | None) -> None:
    if not razorpay_payment_id:
        return
    sb_payment = repository.get_payment_by_razorpay_payment_id(razorpay_payment_id)
    if not sb_payment:
        return
    repository.mark_payment_status(
        payment_id=sb_payment["id"], status=PAYMENT_REFUNDED
    )
    repository.cancel_subscription_for_payment(payment_id=sb_payment["id"])
