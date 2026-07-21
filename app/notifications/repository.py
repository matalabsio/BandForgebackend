"""Service-role persistence for notification workers and webhooks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.db.supabase_client import get_supabase


def claim(*, batch_size: int, lease_seconds: int) -> list[dict[str, Any]]:
    result = get_supabase().rpc(
        "claim_notification_outbox",
        {"p_batch_size": batch_size, "p_lease_seconds": lease_seconds},
    ).execute()
    return list(result.data or [])


def preflight(row: dict[str, Any]) -> bool:
    result = (
        get_supabase()
        .table("speaking_reviews")
        .select("status, approval_version, released_at")
        .eq("id", str(row["review_id"]))
        .limit(1)
        .execute()
    )
    review = result.data[0] if result.data else None
    return bool(
        review
        and review.get("status") == "completed"
        and review.get("released_at")
        and int(review.get("approval_version") or 0) == int(row["approval_version"])
    )


def _leased_update(row: dict[str, Any], values: dict[str, Any]) -> bool:
    result = (
        get_supabase()
        .table("notification_outbox")
        .update(values)
        .eq("id", str(row["id"]))
        .eq("status", "processing")
        .eq("lease_token", str(row["lease_token"]))
        .execute()
    )
    return bool(result.data)


def mark_sent(row: dict[str, Any], provider_message_id: str) -> bool:
    return _leased_update(
        row,
        {
            "status": "sent",
            "provider_message_id": provider_message_id,
            "sent_at": datetime.now(UTC).isoformat(),
            "last_error": None,
            "lease_token": None,
            "lease_expires_at": None,
        },
    )


def mark_cancelled(row: dict[str, Any]) -> bool:
    return _leased_update(
        row,
        {
            "status": "cancelled",
            "cancelled_at": datetime.now(UTC).isoformat(),
            "lease_token": None,
            "lease_expires_at": None,
        },
    )


def mark_failure(
    row: dict[str, Any], *, error: str, retryable: bool, next_attempt_at: str | None
) -> bool:
    terminal = not retryable or int(row["attempts"]) >= int(row["max_attempts"])
    return _leased_update(
        row,
        {
            "status": "failed" if terminal else "retry",
            "failed_at": datetime.now(UTC).isoformat() if terminal else None,
            "next_attempt_at": next_attempt_at,
            "last_error": error[:500],
            "lease_token": None,
            "lease_expires_at": None,
        },
    )


def record_delivery_event(
    *,
    provider_event_id: str,
    provider_message_id: str,
    delivery_status: str,
    occurred_at: str | None,
    payload: dict[str, Any],
) -> bool:
    result = get_supabase().rpc(
        "record_notification_delivery_event",
        {
            "p_provider": "meta",
            "p_provider_event_id": provider_event_id,
            "p_provider_message_id": provider_message_id,
            "p_status": delivery_status,
            "p_occurred_at": occurred_at,
            "p_payload": payload,
        },
    ).execute()
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else False
    return bool(data)
