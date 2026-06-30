"""Admin payments: revenue metrics, payment list, subscription list."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.db.supabase_client import get_supabase


class AdminPaymentItem(BaseModel):
    id: UUID
    student_name: str | None = None
    student_email: str | None = None
    plan_name: str | None = None
    amount: int
    currency: str
    status: str
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    created_at: datetime


class AdminPaymentsResponse(BaseModel):
    items: list[AdminPaymentItem]
    total: int
    page: int
    page_size: int


class AdminSubscriptionItem(BaseModel):
    id: UUID
    student_name: str | None = None
    student_email: str | None = None
    plan_name: str | None = None
    status: str
    starts_at: datetime | None = None
    expires_at: datetime | None = None


class AdminSubscriptionsResponse(BaseModel):
    items: list[AdminSubscriptionItem]
    total: int
    page: int
    page_size: int


class AdminPaymentMetrics(BaseModel):
    revenue_total: int = 0
    revenue_30d: int = 0
    paid_count: int = 0
    active_subscriptions: int = 0


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def list_payments(
    *, status_filter: str | None = None, page: int = 1, page_size: int = 25
) -> AdminPaymentsResponse:
    sb = get_supabase()
    query = sb.table("payments").select(
        "id, amount, currency, status, razorpay_order_id, razorpay_payment_id, "
        "created_at, plans(name), users(full_name, email)",
        count="exact",
    )
    if status_filter:
        query = query.eq("status", status_filter)
    offset = max(0, (page - 1) * page_size)
    result = (
        query.order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
        .execute()
    )
    rows = result.data or []
    items: list[AdminPaymentItem] = []
    for row in rows:
        plan = row.get("plans") or {}
        user = row.get("users") or {}
        items.append(
            AdminPaymentItem(
                id=UUID(str(row["id"])),
                student_name=user.get("full_name"),
                student_email=user.get("email"),
                plan_name=plan.get("name"),
                amount=int(row["amount"]),
                currency=str(row["currency"]),
                status=str(row["status"]),
                razorpay_order_id=row.get("razorpay_order_id"),
                razorpay_payment_id=row.get("razorpay_payment_id"),
                created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
            )
        )
    return AdminPaymentsResponse(
        items=items,
        total=int(result.count or len(items)),
        page=page,
        page_size=page_size,
    )


def list_subscriptions(
    *, status_filter: str | None = None, page: int = 1, page_size: int = 25
) -> AdminSubscriptionsResponse:
    sb = get_supabase()
    query = sb.table("subscriptions").select(
        "id, status, starts_at, expires_at, plans(name), users(full_name, email)",
        count="exact",
    )
    if status_filter:
        query = query.eq("status", status_filter)
    offset = max(0, (page - 1) * page_size)
    result = (
        query.order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
        .execute()
    )
    rows = result.data or []
    items: list[AdminSubscriptionItem] = []
    for row in rows:
        plan = row.get("plans") or {}
        user = row.get("users") or {}
        items.append(
            AdminSubscriptionItem(
                id=UUID(str(row["id"])),
                student_name=user.get("full_name"),
                student_email=user.get("email"),
                plan_name=plan.get("name"),
                status=str(row["status"]),
                starts_at=_parse_dt(row.get("starts_at")),
                expires_at=_parse_dt(row.get("expires_at")),
            )
        )
    return AdminSubscriptionsResponse(
        items=items,
        total=int(result.count or len(items)),
        page=page,
        page_size=page_size,
    )


def get_payment_metrics() -> AdminPaymentMetrics:
    sb = get_supabase()
    paid = (
        sb.table("payments")
        .select("amount, created_at", count="exact")
        .eq("status", "paid")
        .execute()
    )
    rows = paid.data or []
    cutoff = datetime.now(UTC) - timedelta(days=30)
    revenue_total = 0
    revenue_30d = 0
    for row in rows:
        amount = int(row.get("amount") or 0)
        revenue_total += amount
        created = _parse_dt(row.get("created_at"))
        if created and created >= cutoff:
            revenue_30d += amount

    now_iso = datetime.now(UTC).isoformat()
    active = (
        sb.table("subscriptions")
        .select("id", count="exact")
        .eq("status", "active")
        .gt("expires_at", now_iso)
        .execute()
    )
    return AdminPaymentMetrics(
        revenue_total=revenue_total,
        revenue_30d=revenue_30d,
        paid_count=int(paid.count or len(rows)),
        active_subscriptions=int(active.count or 0),
    )
