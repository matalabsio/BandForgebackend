"""Pydantic schemas for the payments module.

Data minimization: the only objects ever sent to Razorpay are
``RazorpayOrderPayload`` (amount/currency/opaque receipt) and ``CheckoutContact``
(name/email/contact for prefill). No learning, diagnostic, behavioural data,
plan slug, or internal IDs leave Supabase.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.payments.constants import DEFAULT_CURRENCY


# --- Razorpay-bound objects (minimal) -------------------------------------


class RazorpayOrderPayload(BaseModel):
    """Only fields passed to client.order.create(). No user_id, no plan_slug."""

    amount: int = Field(gt=0)
    currency: str = DEFAULT_CURRENCY
    receipt: str  # opaque, e.g. secrets.token_hex(8) — NOT user_id or plan slug


class CheckoutContact(BaseModel):
    """Prefill data for the Razorpay checkout widget. Nothing else."""

    name: str | None = None
    email: str | None = None
    contact: str | None = None


# --- Internal Supabase-only context ---------------------------------------


class PaymentContext(BaseModel):
    """Internal mapping, never serialized to Razorpay."""

    user_id: UUID
    plan_id: UUID
    razorpay_order_id: str


# --- API request/response --------------------------------------------------


class PlanOut(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str | None = None
    amount: int
    currency: str
    duration_days: int
    sort_order: int = 0


class PlansResponse(BaseModel):
    plans: list[PlanOut]


class CreateOrderRequest(BaseModel):
    plan_slug: str = Field(min_length=1, max_length=80)


class CreateOrderResponse(BaseModel):
    order_id: str
    key_id: str
    amount: int
    currency: str
    plan_name: str
    checkout_contact: CheckoutContact


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=1)
    razorpay_payment_id: str = Field(min_length=1)
    razorpay_signature: str = Field(min_length=1)


class SubscriptionOut(BaseModel):
    is_active: bool = False
    plan_slug: str | None = None
    plan_name: str | None = None
    status: str | None = None
    starts_at: datetime | None = None
    expires_at: datetime | None = None


class VerifyPaymentResponse(BaseModel):
    ok: bool = True
    subscription: SubscriptionOut


class PaymentHistoryItem(BaseModel):
    id: UUID
    plan_name: str | None = None
    amount: int
    currency: str
    status: str
    created_at: datetime


class PaymentHistoryResponse(BaseModel):
    payments: list[PaymentHistoryItem]


class WebhookResponse(BaseModel):
    ok: bool = True
