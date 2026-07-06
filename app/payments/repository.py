"""Supabase accessors for the payments module."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.db.supabase_client import execute_with_retry, get_supabase
from app.payments.constants import (
    EVENT_FAILED,
    EVENT_PENDING,
    EVENT_PROCESSED,
    PAYMENT_PAID,
    SUBSCRIPTION_CANCELLED,
)

logger = logging.getLogger(__name__)

PLAN_COLUMNS = (
    "id, slug, name, description, amount, currency, duration_days, "
    "is_active, sort_order"
)


def _exec(query):
    return execute_with_retry(query.execute)


def list_active_plans() -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("plans")
        .select(PLAN_COLUMNS)
        .eq("is_active", True)
        .order("sort_order")
        .execute()
    )
    return list(result.data or [])


def get_plan_by_slug(slug: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("plans")
        .select(PLAN_COLUMNS)
        .eq("slug", slug)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def get_plan_by_id(plan_id: str | UUID) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("plans")
        .select(PLAN_COLUMNS)
        .eq("id", str(plan_id))
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def insert_payment(
    *,
    user_id: UUID,
    plan_id: str | UUID,
    razorpay_order_id: str,
    amount: int,
    currency: str,
) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("payments")
        .insert(
            {
                "user_id": str(user_id),
                "plan_id": str(plan_id),
                "razorpay_order_id": razorpay_order_id,
                "amount": amount,
                "currency": currency,
                "status": "created",
            }
        )
        .execute()
    )
    return (result.data or [{}])[0]


def get_payment_by_order_id(razorpay_order_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("payments")
        .select("*")
        .eq("razorpay_order_id", razorpay_order_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def mark_payment_status(
    *,
    payment_id: str | UUID,
    status: str,
    razorpay_payment_id: str | None = None,
    razorpay_signature: str | None = None,
) -> dict[str, Any] | None:
    sb = get_supabase()
    patch: dict[str, Any] = {
        "status": status,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if razorpay_payment_id is not None:
        patch["razorpay_payment_id"] = razorpay_payment_id
    if razorpay_signature is not None:
        patch["razorpay_signature"] = razorpay_signature
    result = (
        sb.table("payments").update(patch).eq("id", str(payment_id)).execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def list_payments_for_user(user_id: UUID, *, limit: int = 50) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("payments")
        .select("id, amount, currency, status, created_at, razorpay_payment_id, plans(name)")
        .eq("user_id", str(user_id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(result.data or [])


# --- subscriptions ---------------------------------------------------------


def get_active_subscription(user_id: UUID) -> dict[str, Any] | None:
    sb = get_supabase()
    now_iso = datetime.now(UTC).isoformat()
    result = (
        sb.table("subscriptions")
        .select("*, plans(slug, name)")
        .eq("user_id", str(user_id))
        .eq("status", "active")
        .gt("expires_at", now_iso)
        .order("expires_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def insert_subscription(
    *,
    user_id: UUID,
    plan_id: str | UUID,
    payment_id: str | UUID,
    starts_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("subscriptions")
        .insert(
            {
                "user_id": str(user_id),
                "plan_id": str(plan_id),
                "payment_id": str(payment_id),
                "starts_at": starts_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "status": "active",
            }
        )
        .execute()
    )
    return (result.data or [{}])[0]


def confirm_payment_paid_bundle(
    *,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str | None,
    starts_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    """Atomically mark payment paid and insert subscription. Falls back sequentially."""
    client = get_supabase()
    try:
        result = _exec(
            client.rpc(
                "confirm_payment_paid_bundle",
                {
                    "p_razorpay_order_id": razorpay_order_id,
                    "p_razorpay_payment_id": razorpay_payment_id,
                    "p_razorpay_signature": razorpay_signature or "",
                    "p_starts_at": starts_at.isoformat(),
                    "p_expires_at": expires_at.isoformat(),
                },
            )
        )
        data = result.data
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        msg = str(exc).lower()
        if "payment_not_found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found.") from exc
        if "plan_not_found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found.") from exc
        logger.warning(
            "confirm_payment_paid_bundle RPC unavailable, using sequential fallback: %s",
            exc,
        )

    return _confirm_payment_paid_sequential(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
        starts_at=starts_at,
        expires_at=expires_at,
    )


def _confirm_payment_paid_sequential(
    *,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str | None,
    starts_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    payment = get_payment_by_order_id(razorpay_order_id)
    if not payment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found.")
    if payment["status"] == PAYMENT_PAID:
        return {
            "already_paid": True,
            "payment_id": payment["id"],
            "user_id": payment["user_id"],
        }
    if not payment.get("plan_id"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found.")

    mark_payment_status(
        payment_id=payment["id"],
        status=PAYMENT_PAID,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
    )
    sub = insert_subscription(
        user_id=UUID(str(payment["user_id"])),
        plan_id=payment["plan_id"],
        payment_id=payment["id"],
        starts_at=starts_at,
        expires_at=expires_at,
    )
    return {
        "already_paid": False,
        "payment_id": payment["id"],
        "subscription_id": sub.get("id"),
        "user_id": payment["user_id"],
    }


def cancel_subscription_for_payment(*, payment_id: str | UUID) -> None:
    """Revoke access when a payment is refunded."""
    sb = get_supabase()
    now_iso = datetime.now(UTC).isoformat()
    sb.table("subscriptions").update(
        {
            "status": SUBSCRIPTION_CANCELLED,
            "expires_at": now_iso,
        }
    ).eq("payment_id", str(payment_id)).eq("status", "active").execute()


# --- payment_events (idempotency log) --------------------------------------


def insert_payment_event(
    *,
    razorpay_event_id: str | None,
    event_type: str,
    razorpay_order_id: str | None = None,
    razorpay_payment_id: str | None = None,
    payload: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Insert a webhook event as pending. Returns None if event id already exists."""
    sb = get_supabase()
    row: dict[str, Any] = {
        "razorpay_event_id": razorpay_event_id,
        "event_type": event_type,
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "payload": payload,
        "raw_payload": payload,
        "headers": headers,
        "processing_status": EVENT_PENDING,
        "received_at": datetime.now(UTC).isoformat(),
    }
    try:
        result = sb.table("payment_events").insert(row).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if razorpay_event_id and (
            "duplicate" in msg
            or "unique" in msg
            or "23505" in msg
            or "already exists" in msg
        ):
            return None
        raise
    return (result.data or [{}])[0]


def mark_event_processed(event_id: str | UUID) -> None:
    sb = get_supabase()
    sb.table("payment_events").update(
        {
            "processed_at": datetime.now(UTC).isoformat(),
            "processing_status": EVENT_PROCESSED,
        }
    ).eq("id", str(event_id)).execute()


def mark_event_failed(event_id: str | UUID, *, error: str) -> None:
    sb = get_supabase()
    sb.table("payment_events").update(
        {
            "processing_status": EVENT_FAILED,
            "processing_error": error[:2000],
        }
    ).eq("id", str(event_id)).execute()


def get_payment_by_razorpay_payment_id(
    razorpay_payment_id: str,
) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("payments")
        .select("*")
        .eq("razorpay_payment_id", razorpay_payment_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None
