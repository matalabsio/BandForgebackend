"""Structured JSON logs for the payments module.

Phase 2 catalog events (uvicorn stdout): CREATE_ORDER, VERIFY_RECEIVED,
SIGNATURE_VALID, PAYMENT_LOOKUP, RPC_*, FALLBACK_*, SUBSCRIPTION_*,
VERIFY_SUCCESS.

Phase 4 create-order persistence events: RAZORPAY_ORDER_CREATED,
PAYMENT_INSERTED, DB_CONSISTENCY_CHECK, DB_CONSISTENCY_OK,
DB_CONSISTENCY_FAIL, PAYMENT_PERSISTED (then CREATE_ORDER).

Correlation / common fields: user_id, plan_id, order / razorpay_order,
payment / payment_id, success. On CREATE_ORDER / PAYMENT_PERSISTED,
payment_id is the Supabase payments row id; on later events, payment is
the Razorpay payment id.

Never log secrets, signatures, card/UPI data, or full webhook bodies.

Phase 6 webhook: transient fulfillment failure raises 503; failed
payment_events are reprocessed on duplicate event_id with retry_count.

Phase 7 reconcile: RECONCILE_SCAN / CANDIDATE / APPLIED / SKIPPED / ERROR.

Phase 8 backfill: BACKFILL_SCAN / INSERTED / APPLIED / SKIPPED / ERROR.
"""

from __future__ import annotations

import json
from typing import Any


def payment_log(event: str, **fields: Any) -> None:
    payload: dict[str, Any] = {"event": event, **fields}
    print(json.dumps(payload, default=str))
