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
    PAYMENT_REFUNDED,
    SUBSCRIPTION_CANCELLED,
)
from app.payments.logging import payment_log

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


def count_payments_by_order_id(razorpay_order_id: str) -> int:
    """Count payment rows for an order id (no limit) — used for exactly-one invariant."""
    sb = get_supabase()
    result = (
        sb.table("payments")
        .select("id")
        .eq("razorpay_order_id", razorpay_order_id)
        .execute()
    )
    return len(result.data or [])


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


def list_payments_since(
    since: datetime,
    *,
    statuses: list[str] | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Payments created at or after ``since`` (optional status filter)."""
    sb = get_supabase()
    query = (
        sb.table("payments")
        .select(
            "id, user_id, plan_id, status, amount, currency, "
            "razorpay_order_id, razorpay_payment_id, created_at, updated_at"
        )
        .gte("created_at", since.astimezone(UTC).isoformat())
        .order("created_at", desc=True)
        .limit(limit)
    )
    if statuses:
        query = query.in_("status", statuses)
    result = _exec(query)
    return list(result.data or [])


def list_paid_payments_missing_subscriptions(
    since: datetime,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Paid payments in window with zero subscription rows for payment_id."""
    paid = list_payments_since(since, statuses=[PAYMENT_PAID], limit=limit)
    missing: list[dict[str, Any]] = []
    for row in paid:
        subs = list_subscriptions_for_payment(row["id"])
        if not subs:
            missing.append(row)
    return missing


# --- subscriptions ---------------------------------------------------------


def get_active_subscription(user_id: UUID) -> dict[str, Any] | None:
    from app.cache.hybrid_cache import get_json, set_json

    cache_key = f"sub:active:{user_id}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        if cached.get("__miss__"):
            return None
        return cached

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
    row = rows[0] if rows else None
    # Short TTL: collapses duplicate gates within one navigation (writing start, FSP).
    if row is None:
        set_json(cache_key, {"__miss__": True}, 15)
    else:
        set_json(cache_key, row, 15)
    return row


def invalidate_active_subscription_cache(user_id: UUID | str) -> None:
    from app.cache.hybrid_cache import delete_many

    delete_many([f"sub:active:{user_id}"])


def insert_subscription(
    *,
    user_id: UUID,
    plan_id: str | UUID,
    payment_id: str | UUID,
    starts_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    sb = get_supabase()
    try:
        result = _exec(
            sb.table("subscriptions").insert(
                {
                    "user_id": str(user_id),
                    "plan_id": str(plan_id),
                    "payment_id": str(payment_id),
                    "starts_at": starts_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "status": "active",
                }
            )
        )
        invalidate_active_subscription_cache(user_id)
        return (result.data or [{}])[0]
    except Exception as exc:
        if _is_unique_violation(exc):
            existing = list_subscriptions_for_payment(payment_id)
            if existing:
                invalidate_active_subscription_cache(user_id)
                return existing[0]
        raise


def _is_unique_violation(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "duplicate" in msg
        or "unique" in msg
        or "23505" in msg
        or "already exists" in msg
    )


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
    payment_log(
        "RPC_START",
        order=razorpay_order_id,
        payment=razorpay_payment_id,
    )
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
            payment_log(
                "RPC_SUCCESS",
                order=razorpay_order_id,
                payment=razorpay_payment_id,
                payment_id=str(data.get("payment_id") or ""),
                already_paid=bool(data.get("already_paid")),
            )
            if data.get("already_paid"):
                payment_log(
                    "SUBSCRIPTION_ALREADY_EXISTS",
                    user_id=str(data.get("user_id") or ""),
                    payment_id=str(data.get("payment_id") or ""),
                    order=razorpay_order_id,
                )
            else:
                payment_log(
                    "SUBSCRIPTION_CREATED",
                    user_id=str(data.get("user_id") or ""),
                    payment_id=str(data.get("payment_id") or ""),
                    subscription_id=str(data.get("subscription_id") or ""),
                    order=razorpay_order_id,
                )
            return data
    except Exception as exc:
        msg = str(exc).lower()
        if "payment_not_found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found.") from exc
        if "plan_not_found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found.") from exc
        if "payment_refunded" in msg:
            from app.payments.exceptions import PaymentRefundedError

            raise PaymentRefundedError() from exc
        payment_log(
            "RPC_FAILED",
            order=razorpay_order_id,
            payment=razorpay_payment_id,
            error=str(exc)[:500],
        )
        logger.warning(
            "confirm_payment_paid_bundle RPC unavailable, using sequential fallback: %s",
            exc,
        )

    payment_log(
        "FALLBACK_START",
        order=razorpay_order_id,
        payment=razorpay_payment_id,
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
    """Best-effort recovery when RPC is unavailable — not a second business path."""
    payment = get_payment_by_order_id(razorpay_order_id)
    if not payment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found.")

    if str(payment.get("status") or "") == PAYMENT_REFUNDED:
        from app.payments.exceptions import PaymentRefundedError

        raise PaymentRefundedError()

    existing_subs = list_subscriptions_for_payment(payment["id"])
    if existing_subs:
        out = {
            "already_paid": True,
            "payment_id": payment["id"],
            "user_id": payment["user_id"],
            "subscription_id": existing_subs[0].get("id"),
        }
        payment_log(
            "FALLBACK_SUCCESS",
            order=razorpay_order_id,
            payment=razorpay_payment_id,
            already_paid=True,
        )
        payment_log(
            "SUBSCRIPTION_ALREADY_EXISTS",
            user_id=str(payment["user_id"]),
            payment_id=str(payment["id"]),
            order=razorpay_order_id,
        )
        return out

    if not payment.get("plan_id"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found.")

    if payment["status"] != PAYMENT_PAID:
        mark_payment_status(
            payment_id=payment["id"],
            status=PAYMENT_PAID,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
        )
    elif razorpay_payment_id and not payment.get("razorpay_payment_id"):
        mark_payment_status(
            payment_id=payment["id"],
            status=PAYMENT_PAID,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
        )

    # Recompute stacking immediately before insert (best-effort if RPC unavailable).
    plan = get_plan_by_id(payment["plan_id"])
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found.")
    from app.payments.service import _compute_subscription_dates

    stacked_starts, stacked_expires = _compute_subscription_dates(
        UUID(str(payment["user_id"])), plan
    )

    sub = insert_subscription(
        user_id=UUID(str(payment["user_id"])),
        plan_id=payment["plan_id"],
        payment_id=payment["id"],
        starts_at=stacked_starts,
        expires_at=stacked_expires,
    )
    out = {
        "already_paid": payment["status"] == PAYMENT_PAID,
        "payment_id": payment["id"],
        "subscription_id": sub.get("id"),
        "user_id": payment["user_id"],
    }
    payment_log(
        "FALLBACK_SUCCESS",
        order=razorpay_order_id,
        payment=razorpay_payment_id,
        already_paid=bool(out["already_paid"]),
    )
    payment_log(
        "SUBSCRIPTION_CREATED",
        user_id=str(payment["user_id"]),
        payment_id=str(payment["id"]),
        subscription_id=str(sub.get("id") or ""),
        order=razorpay_order_id,
    )
    return out


def cancel_subscription_for_payment(*, payment_id: str | UUID) -> None:
    """Revoke access when a payment is refunded."""
    sb = get_supabase()
    now_iso = datetime.now(UTC).isoformat()
    # Fetch user ids before update so we can bust entitlement cache.
    prior = (
        sb.table("subscriptions")
        .select("user_id")
        .eq("payment_id", str(payment_id))
        .eq("status", "active")
        .execute()
    ).data or []
    sb.table("subscriptions").update(
        {
            "status": SUBSCRIPTION_CANCELLED,
            "expires_at": now_iso,
        }
    ).eq("payment_id", str(payment_id)).eq("status", "active").execute()
    for row in prior:
        uid = row.get("user_id")
        if uid:
            invalidate_active_subscription_cache(uid)


def delete_subscriptions_for_payment(*, payment_id: str | UUID) -> int:
    """Hard-delete subscription rows for a payment (ops drill / repair only)."""
    sb = get_supabase()
    result = (
        sb.table("subscriptions")
        .delete()
        .eq("payment_id", str(payment_id))
        .execute()
    )
    return len(result.data or [])


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
    _exec(
        sb.table("payment_events").update(
            {
                "processed_at": datetime.now(UTC).isoformat(),
                "processing_status": EVENT_PROCESSED,
                "processing_error": None,
            }
        ).eq("id", str(event_id))
    )


def mark_event_failed(event_id: str | UUID, *, error: str) -> None:
    sb = get_supabase()
    _exec(
        sb.table("payment_events").update(
            {
                "processing_status": EVENT_FAILED,
                "processing_error": error[:2000],
            }
        ).eq("id", str(event_id))
    )


def get_payment_event_by_razorpay_event_id(
    razorpay_event_id: str,
) -> dict[str, Any] | None:
    sb = get_supabase()
    result = _exec(
        sb.table("payment_events")
        .select(
            "id, razorpay_event_id, event_type, razorpay_order_id, "
            "razorpay_payment_id, processing_status, processing_error, "
            "retry_count, received_at, processed_at, created_at"
        )
        .eq("razorpay_event_id", razorpay_event_id)
        .limit(1)
    )
    rows = result.data or []
    return rows[0] if rows else None


def claim_payment_event_for_retry(event_id: str | UUID) -> dict[str, Any]:
    """Bump retry_count and reset status to pending for reprocessing."""
    existing = None
    sb = get_supabase()
    got = _exec(
        sb.table("payment_events")
        .select("id, retry_count")
        .eq("id", str(event_id))
        .limit(1)
    )
    rows = got.data or []
    existing = rows[0] if rows else None
    next_retry = int((existing or {}).get("retry_count") or 0) + 1
    result = _exec(
        sb.table("payment_events").update(
            {
                "retry_count": next_retry,
                "processing_status": EVENT_PENDING,
                "processing_error": None,
            }
        ).eq("id", str(event_id))
    )
    updated = (result.data or [{}])[0]
    if not updated.get("id"):
        return {
            "id": str(event_id),
            "retry_count": next_retry,
            "processing_status": EVENT_PENDING,
        }
    return updated


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


def list_subscriptions_for_payment(
    payment_id: str | UUID,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("subscriptions")
        .select("id, user_id, plan_id, payment_id, status, starts_at, expires_at, created_at")
        .eq("payment_id", str(payment_id))
        .order("created_at", desc=True)
        .execute()
    )
    return list(result.data or [])


def list_payment_events_for_order(
    razorpay_order_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("payment_events")
        .select(
            "id, razorpay_event_id, event_type, razorpay_order_id, "
            "razorpay_payment_id, processing_status, processing_error, "
            "received_at, processed_at, created_at"
        )
        .eq("razorpay_order_id", razorpay_order_id)
        .order("received_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(result.data or [])


def list_payment_events_for_payment_id(
    razorpay_payment_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("payment_events")
        .select(
            "id, razorpay_event_id, event_type, razorpay_order_id, "
            "razorpay_payment_id, processing_status, processing_error, "
            "received_at, processed_at, created_at"
        )
        .eq("razorpay_payment_id", razorpay_payment_id)
        .order("received_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(result.data or [])
