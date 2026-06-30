"""Thin Razorpay wrapper.

Order creation goes through the official SDK; signature verification is done
locally with HMAC so it has no hard dependency on the SDK and is trivially
testable. Only ``RazorpayOrderPayload`` data is ever sent to Razorpay.
"""

from __future__ import annotations

import hashlib
import hmac
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.payments.exceptions import PaymentsDisabledError
from app.payments.schemas import RazorpayOrderPayload


@lru_cache
def _client() -> Any:
    settings = get_settings()
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        raise PaymentsDisabledError()
    import razorpay  # lazy import; only needed for live order creation

    return razorpay.Client(
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
    )


def create_order(payload: RazorpayOrderPayload) -> dict[str, Any]:
    """Create a Razorpay order from a minimal payload.

    No ``notes`` are attached — user_id, plan_slug, and product metadata stay
    in Supabase.
    """
    client = _client()
    return client.order.create(
        {
            "amount": payload.amount,
            "currency": payload.currency,
            "receipt": payload.receipt,
            "payment_capture": 1,
        }
    )


def verify_payment_signature(
    *,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """Verify the checkout handler signature: HMAC_SHA256(order_id|payment_id)."""
    settings = get_settings()
    secret = settings.razorpay_key_secret
    if not secret:
        return False
    message = f"{razorpay_order_id}|{razorpay_payment_id}".encode()
    expected = hmac.new(
        secret.encode(), message, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, razorpay_signature)


def verify_webhook_signature(*, raw_body: bytes, signature: str) -> bool:
    """Verify a webhook using the raw request body and the webhook secret."""
    settings = get_settings()
    secret = settings.razorpay_webhook_secret
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
