"""Shared constants for the payments module."""

from __future__ import annotations

# payments.status
PAYMENT_CREATED = "created"
PAYMENT_PAID = "paid"
PAYMENT_FAILED = "failed"
PAYMENT_REFUNDED = "refunded"

# subscriptions.status
SUBSCRIPTION_ACTIVE = "active"
SUBSCRIPTION_EXPIRED = "expired"
SUBSCRIPTION_CANCELLED = "cancelled"

# Razorpay webhook event types we act on.
EVENT_PAYMENT_CAPTURED = "payment.captured"
EVENT_PAYMENT_FAILED = "payment.failed"
EVENT_REFUND_CREATED = "refund.created"

# Ops recovery (payment_events.event_type)
EVENT_BACKFILL = "bandforge.backfill"

# payment_events.processing_status
EVENT_PENDING = "pending"
EVENT_PROCESSED = "processed"
EVENT_FAILED = "failed"

DEFAULT_CURRENCY = "INR"

WRITING_SKILL_SLUG = "writing_skill"
FULL_SKILL_PROGRAM_SLUG = "full_skill_program"
WRITING_SKILL_DEFAULT_MOCK_QUOTA = 1
