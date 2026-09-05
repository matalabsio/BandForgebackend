"""Periodic reconciliation: Razorpay captures vs Supabase fulfillment.

Dry-run by default; with ``apply=True`` replays ``confirm_payment_paid`` for
repairable stuck states. Never invents missing ``payments`` rows.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.payments import razorpay_client, repository, service
from app.payments.constants import PAYMENT_CREATED, PAYMENT_PAID
from app.payments.logging import payment_log

VERDICT_OK = "OK"
VERDICT_VERIFY = "STUCK_AT_verify"
VERDICT_SUBSCRIPTION = "STUCK_AT_subscription"
VERDICT_CREATE_ROW = "STUCK_AT_create_row_missing"
VERDICT_UNKNOWN = "STUCK_AT_unknown"


@dataclass
class ReconcileCandidate:
    verdict: str
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    local_payment_id: str | None = None
    local_status: str | None = None
    amount: int | None = None
    action: str = "skip"  # skip | apply | report_only
    error: str | None = None
    applied: bool = False


@dataclass
class ReconcileReport:
    hours: int
    apply: bool
    scanned_razorpay: int = 0
    scanned_local: int = 0
    candidates: list[ReconcileCandidate] = field(default_factory=list)
    applied_ok: int = 0
    applied_errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hours": self.hours,
            "apply": self.apply,
            "scanned_razorpay": self.scanned_razorpay,
            "scanned_local": self.scanned_local,
            "applied_ok": self.applied_ok,
            "applied_errors": self.applied_errors,
            "candidates": [asdict(c) for c in self.candidates],
        }


def _is_captured(rzp_payment: dict[str, Any]) -> bool:
    if rzp_payment.get("captured") is True:
        return True
    return str(rzp_payment.get("status") or "").lower() == "captured"


def _classify(
    *,
    local: dict[str, Any] | None,
    rzp_captured: bool,
    has_subscription: bool,
) -> tuple[str, str]:
    """Return (verdict, action)."""
    if local is None:
        if rzp_captured:
            return VERDICT_CREATE_ROW, "report_only"
        return VERDICT_UNKNOWN, "skip"

    status = str(local.get("status") or "")
    if status == PAYMENT_PAID and has_subscription:
        return VERDICT_OK, "skip"
    if status == PAYMENT_PAID and not has_subscription:
        return VERDICT_SUBSCRIPTION, "apply"
    if rzp_captured and status == PAYMENT_CREATED:
        return VERDICT_VERIFY, "apply"
    if status == PAYMENT_CREATED and not rzp_captured:
        return VERDICT_OK, "skip"  # still at checkout — not a reconcile target
    if rzp_captured and status not in (PAYMENT_PAID,):
        return VERDICT_VERIFY, "apply"
    return VERDICT_UNKNOWN, "skip"


def run_reconcile(*, hours: int = 48, apply: bool = False) -> ReconcileReport:
    hours = max(1, int(hours))
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    from_ts = int(since.timestamp())
    to_ts = int(now.timestamp())

    report = ReconcileReport(hours=hours, apply=apply)
    payment_log(
        "RECONCILE_SCAN",
        hours=hours,
        apply=apply,
        since=since.isoformat(),
    )

    by_order: dict[str, dict[str, Any]] = {}

    rzp_items: list[dict[str, Any]] = []
    if razorpay_client.credentials_ready():
        try:
            rzp_items = razorpay_client.list_recent_payments(
                from_ts=from_ts, to_ts=to_ts
            )
        except Exception as exc:  # noqa: BLE001
            payment_log("RECONCILE_ERROR", stage="razorpay_list", error=str(exc)[:500])
            raise
    report.scanned_razorpay = len(rzp_items)

    for p in rzp_items:
        if not _is_captured(p):
            continue
        order_id = str(p.get("order_id") or "") or None
        pay_id = str(p.get("id") or "") or None
        key = order_id or pay_id
        if not key:
            continue
        entry = by_order.setdefault(
            key,
            {
                "order_id": order_id,
                "payment_id": pay_id,
                "amount": p.get("amount"),
                "rzp_captured": True,
                "local": None,
            },
        )
        entry["rzp_captured"] = True
        entry["payment_id"] = pay_id or entry.get("payment_id")
        entry["order_id"] = order_id or entry.get("order_id")
        if p.get("amount") is not None:
            entry["amount"] = p.get("amount")

    created_local = repository.list_payments_since(
        since, statuses=[PAYMENT_CREATED], limit=500
    )
    paid_missing = repository.list_paid_payments_missing_subscriptions(since, limit=500)
    all_local = created_local + [
        r for r in paid_missing if str(r["id"]) not in {str(x["id"]) for x in created_local}
    ]
    report.scanned_local = len(all_local)

    for row in all_local:
        order_id = str(row.get("razorpay_order_id") or "") or None
        # Coupon grants never hit Razorpay — skip from capture reconcile.
        if order_id and order_id.startswith("coupon_ord_"):
            continue
        pay_id = str(row.get("razorpay_payment_id") or "") or None
        key = order_id or pay_id or str(row["id"])
        entry = by_order.setdefault(
            key,
            {
                "order_id": order_id,
                "payment_id": pay_id,
                "amount": row.get("amount"),
                "rzp_captured": False,
                "local": row,
            },
        )
        entry["local"] = row
        entry["order_id"] = order_id or entry.get("order_id")
        entry["payment_id"] = pay_id or entry.get("payment_id")

    # Attach local rows for Razorpay-only keys
    for entry in by_order.values():
        if entry.get("local"):
            continue
        local = None
        if entry.get("order_id"):
            local = repository.get_payment_by_order_id(str(entry["order_id"]))
        if local is None and entry.get("payment_id"):
            local = repository.get_payment_by_razorpay_payment_id(
                str(entry["payment_id"])
            )
        entry["local"] = local

    for entry in by_order.values():
        local = entry.get("local")
        has_sub = False
        if local:
            has_sub = bool(repository.list_subscriptions_for_payment(local["id"]))
        verdict, action = _classify(
            local=local,
            rzp_captured=bool(entry.get("rzp_captured")),
            has_subscription=has_sub,
        )
        if verdict == VERDICT_OK and action == "skip":
            # Only emit OK when we had a Razorpay capture or paid-missing interest
            if not entry.get("rzp_captured") and str(
                (local or {}).get("status") or ""
            ) == PAYMENT_CREATED:
                continue

        candidate = ReconcileCandidate(
            verdict=verdict,
            razorpay_order_id=entry.get("order_id"),
            razorpay_payment_id=entry.get("payment_id")
            or (local.get("razorpay_payment_id") if local else None),
            local_payment_id=str(local["id"]) if local else None,
            local_status=str(local["status"]) if local else None,
            amount=int(entry["amount"])
            if entry.get("amount") is not None
            else (int(local["amount"]) if local and local.get("amount") is not None else None),
            action=action,
        )
        payment_log(
            "RECONCILE_CANDIDATE",
            verdict=candidate.verdict,
            action=candidate.action,
            order=candidate.razorpay_order_id,
            payment=candidate.razorpay_payment_id,
            payment_id=candidate.local_payment_id,
        )

        if action == "apply" and apply:
            order_id = candidate.razorpay_order_id
            pay_id = candidate.razorpay_payment_id
            if not order_id or not pay_id:
                candidate.error = "missing_order_or_payment_id"
                candidate.action = "report_only"
                report.applied_errors += 1
                payment_log(
                    "RECONCILE_ERROR",
                    order=order_id,
                    payment=pay_id,
                    error=candidate.error,
                )
            else:
                try:
                    service.confirm_payment_paid(
                        razorpay_order_id=order_id,
                        razorpay_payment_id=pay_id,
                        captured_amount=candidate.amount,
                    )
                    candidate.applied = True
                    report.applied_ok += 1
                    payment_log(
                        "RECONCILE_APPLIED",
                        verdict=candidate.verdict,
                        order=order_id,
                        payment=pay_id,
                        payment_id=candidate.local_payment_id,
                        success=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    candidate.error = str(exc)[:500]
                    report.applied_errors += 1
                    payment_log(
                        "RECONCILE_ERROR",
                        verdict=candidate.verdict,
                        order=order_id,
                        payment=pay_id,
                        error=candidate.error,
                        success=False,
                    )
        elif action == "skip":
            payment_log(
                "RECONCILE_SKIPPED",
                verdict=candidate.verdict,
                order=candidate.razorpay_order_id,
                payment=candidate.razorpay_payment_id,
            )

        report.candidates.append(candidate)

    return report
