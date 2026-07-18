"""Intentional orphan drill: soft-break a paid payment, then repair via reconcile.

Test-mode only. Used by ``scripts/drill_reconcile_repair.py``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import get_settings
from app.payments import repository, service
from app.payments.constants import PAYMENT_CREATED, PAYMENT_PAID
from app.payments.logging import payment_log
from app.payments.reconcile import run_reconcile


class DrillError(Exception):
    """Ops drill refused or failed validation."""


@dataclass
class DrillSnapshot:
    payment_id: str | None = None
    status: str | None = None
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    subscription_count: int = 0


@dataclass
class DrillReport:
    apply: bool
    soft_broke: bool = False
    repaired: bool = False
    before: DrillSnapshot = field(default_factory=DrillSnapshot)
    after_break: DrillSnapshot = field(default_factory=DrillSnapshot)
    after_repair: DrillSnapshot = field(default_factory=DrillSnapshot)
    reconcile_applied_ok: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ensure_test_mode_only() -> None:
    settings = get_settings()
    key_id = (settings.razorpay_key_id or "").strip()
    if key_id.startswith("rzp_live_"):
        raise DrillError("Drill refuses LIVE mode keys (rzp_live_*). Use Test keys only.")
    if settings.app_env.strip().lower() == "production":
        raise DrillError("Drill refuses APP_ENV=production. Run against a test environment.")


def _snapshot(row: dict[str, Any]) -> DrillSnapshot:
    subs = repository.list_subscriptions_for_payment(row["id"])
    return DrillSnapshot(
        payment_id=str(row["id"]),
        status=str(row.get("status") or ""),
        razorpay_order_id=row.get("razorpay_order_id"),
        razorpay_payment_id=row.get("razorpay_payment_id"),
        subscription_count=len(subs),
    )


def _resolve_payment(
    *,
    razorpay_payment_id: str | None,
    razorpay_order_id: str | None,
) -> dict[str, Any]:
    row: dict[str, Any] | None = None
    if razorpay_payment_id:
        row = repository.get_payment_by_razorpay_payment_id(razorpay_payment_id)
    if row is None and razorpay_order_id:
        row = repository.get_payment_by_order_id(razorpay_order_id)
    if row is None:
        raise DrillError("No local payments row for the given payment-id / order-id")
    return row


def soft_break_payment(*, payment: dict[str, Any], apply: bool) -> DrillSnapshot:
    """Set status back to created and delete subscription rows for this payment."""
    status = str(payment.get("status") or "")
    if status != PAYMENT_PAID:
        raise DrillError(
            f"Expected local status={PAYMENT_PAID!r} for soft-break; got {status!r}"
        )
    if not payment.get("razorpay_payment_id"):
        raise DrillError("Payment row missing razorpay_payment_id — cannot soft-break safely")

    if not apply:
        return _snapshot(payment)

    deleted = repository.delete_subscriptions_for_payment(payment_id=payment["id"])
    updated = repository.mark_payment_status(
        payment_id=payment["id"],
        status=PAYMENT_CREATED,
    )
    payment_log(
        "DRILL_SOFT_BREAK",
        payment_id=str(payment["id"]),
        order=str(payment.get("razorpay_order_id") or ""),
        deleted_subscriptions=deleted,
    )
    return _snapshot(updated or payment)


def run_drill(
    *,
    razorpay_payment_id: str | None = None,
    razorpay_order_id: str | None = None,
    apply: bool = False,
    hours: int = 168,
    i_understand_test_only: bool = False,
) -> DrillReport:
    if not i_understand_test_only:
        raise DrillError("Pass --i-understand-test-only to acknowledge Test-only drill risk")
    if not razorpay_payment_id and not razorpay_order_id:
        raise DrillError("Provide --payment-id and/or --order-id")

    _ensure_test_mode_only()

    report = DrillReport(apply=apply)
    row = _resolve_payment(
        razorpay_payment_id=razorpay_payment_id,
        razorpay_order_id=razorpay_order_id,
    )
    report.before = _snapshot(row)

    if not apply:
        report.after_break = soft_break_payment(payment=row, apply=False)
        report.error = None
        payment_log(
            "DRILL_DRY_RUN",
            payment_id=str(row["id"]),
            order=str(row.get("razorpay_order_id") or ""),
        )
        return report

    report.after_break = soft_break_payment(payment=row, apply=True)
    report.soft_broke = True

    # Prefer confirm when we already have the Razorpay payment id on the row.
    rzp_pid = str(row.get("razorpay_payment_id") or "")
    rzp_oid = str(row.get("razorpay_order_id") or "")
    try:
        service.confirm_payment_paid(
            razorpay_order_id=rzp_oid,
            razorpay_payment_id=rzp_pid,
        )
        report.repaired = True
    except Exception as exc:
        recon = run_reconcile(hours=hours, apply=True)
        report.reconcile_applied_ok = recon.applied_ok
        if recon.applied_ok < 1:
            report.error = f"confirm failed ({exc}); reconcile applied_ok=0"
            refreshed = repository.get_payment_by_order_id(rzp_oid) or row
            report.after_repair = _snapshot(refreshed)
            return report
        report.repaired = True
        report.error = f"confirm failed ({exc}); repaired via reconcile"

    refreshed = repository.get_payment_by_order_id(rzp_oid)
    if refreshed is None:
        refreshed = repository.get_payment_by_razorpay_payment_id(rzp_pid) or row
    report.after_repair = _snapshot(refreshed)

    if (
        report.after_repair.status != PAYMENT_PAID
        or report.after_repair.subscription_count < 1
    ):
        report.repaired = False
        report.error = (
            report.error
            or "Repair incomplete: expected paid + subscription after confirm/reconcile"
        )

    payment_log(
        "DRILL_REPAIR",
        payment_id=str(report.after_repair.payment_id or ""),
        order=rzp_oid,
        repaired=report.repaired,
        error=report.error or "",
    )
    return report
