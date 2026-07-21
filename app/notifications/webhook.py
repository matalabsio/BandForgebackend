"""Meta webhook verification and delivery status ingestion."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.config import get_settings
from app.notifications import repository


def verify_challenge(*, mode: str | None, token: str | None, challenge: str | None) -> str:
    expected = get_settings().meta_whatsapp_verify_token
    if (
        not expected
        or mode != "subscribe"
        or token is None
        or not hmac.compare_digest(token, expected)
        or challenge is None
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Webhook verification failed.")
    return challenge


def verify_signature(raw_body: bytes, signature: str | None) -> None:
    secret = get_settings().meta_whatsapp_app_secret
    if not secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Webhook is not configured."
        )
    expected = "sha256=" + hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature.")


def _occurred_at(timestamp: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(timestamp), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def process_payload(payload: dict[str, Any]) -> int:
    processed = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            statuses = (change.get("value") or {}).get("statuses") or []
            for item in statuses:
                message_id = str(item.get("id") or "")
                delivery_status = str(item.get("status") or "")
                timestamp = str(item.get("timestamp") or "")
                if not message_id or delivery_status not in {
                    "sent",
                    "delivered",
                    "read",
                    "failed",
                }:
                    continue
                event_id = f"{message_id}:{delivery_status}:{timestamp}"
                error_codes = [
                    str(error.get("code"))
                    for error in item.get("errors") or []
                    if isinstance(error, dict) and error.get("code") is not None
                ]
                if repository.record_delivery_event(
                    provider_event_id=event_id,
                    provider_message_id=message_id,
                    delivery_status=delivery_status,
                    occurred_at=_occurred_at(timestamp),
                    payload={"status": delivery_status, "error_codes": error_codes},
                ):
                    processed += 1
    return processed
