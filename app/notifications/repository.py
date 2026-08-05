"""Service-role persistence for notification workers and webhooks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.supabase_client import get_supabase


def outbox_ops_snapshot() -> dict[str, Any]:
    """Queued depth, failures in last 24h, and queued counts by channel."""
    sb = get_supabase()
    queued_statuses = ("queued", "retry", "processing")
    queued = 0
    by_channel: dict[str, int] = {}
    failed_24h = 0

    try:
        q = (
            sb.table("notification_outbox")
            .select("id", count="exact")
            .in_("status", list(queued_statuses))
            .limit(1)
            .execute()
        )
        queued = int(getattr(q, "count", None) or 0)
    except Exception:
        queued = 0

    try:
        rows = (
            sb.table("notification_outbox")
            .select("channel")
            .in_("status", list(queued_statuses))
            .execute()
        ).data or []
        for row in rows:
            ch = str(row.get("channel") or "unknown")
            by_channel[ch] = int(by_channel.get(ch, 0)) + 1
    except Exception:
        by_channel = {}

    try:
        since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        f = (
            sb.table("notification_outbox")
            .select("id", count="exact")
            .eq("status", "failed")
            .gte("failed_at", since)
            .limit(1)
            .execute()
        )
        failed_24h = int(getattr(f, "count", None) or 0)
    except Exception:
        failed_24h = 0

    return {
        "queued": queued,
        "failed_24h": failed_24h,
        "by_channel": by_channel,
    }


def claim(*, batch_size: int, lease_seconds: int) -> list[dict[str, Any]]:
    result = get_supabase().rpc(
        "claim_notification_outbox",
        {"p_batch_size": batch_size, "p_lease_seconds": lease_seconds},
    ).execute()
    return list(result.data or [])


def preflight(row: dict[str, Any]) -> bool:
    event_type = str(row.get("event_type") or "")
    if event_type == "learning.daily_reminder":
        return True
    review_id = row.get("review_id")
    if not review_id:
        return False
    result = (
        get_supabase()
        .table("speaking_reviews")
        .select("status, approval_version, released_at")
        .eq("id", str(review_id))
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


def already_enqueued_plan_reminder(
    *, user_id: str, local_date: str, channel: str = "email"
) -> bool:
    result = (
        get_supabase()
        .table("notification_outbox")
        .select("id")
        .eq("user_id", str(user_id))
        .eq("event_type", "learning.daily_reminder")
        .eq("idempotency_date", local_date)
        .eq("channel", channel)
        .limit(1)
        .execute()
    )
    return bool(result.data)


def enqueue_plan_reminder(
    *,
    user_id: str,
    email: str,
    local_date: str,
    payload: dict[str, Any],
) -> bool:
    """Insert learning.daily_reminder email job. Returns True when a new row was created."""
    if already_enqueued_plan_reminder(user_id=user_id, local_date=local_date):
        return False
    row = {
        "event_type": "learning.daily_reminder",
        "user_id": str(user_id),
        "idempotency_date": local_date,
        "channel": "email",
        "recipient_snapshot": email.strip().lower(),
        "payload": payload,
        "template_version": "learning_daily_reminder_email_v1",
        "status": "queued",
    }
    try:
        result = get_supabase().table("notification_outbox").insert(row).execute()
        return bool(result.data)
    except Exception:
        # Unique index race: another worker/sweep already inserted today.
        return False


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
