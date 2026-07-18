"""Ops orphan backfill: reconstruct missing payments row then fulfill.

Identity (user_id + plan_slug) must be supplied by ops — Razorpay orders carry
no notes. Never write subscriptions directly; always use confirm_payment_paid.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from app.payments import razorpay_client, repository, service
from app.payments.constants import (
    EVENT_BACKFILL,
    PAYMENT_CREATED,
    PAYMENT_PAID,
)
from app.payments.exceptions import PaymentAmountMismatchError, PlanNotFoundError
from app.payments.logging import payment_log


class BackfillError(Exception):
    """Fatal backfill precondition failure (bad merchant/amount/missing capture)."""


@dataclass
class BackfillSuggest:
    email: str | None = None
    contact: str | None = None
    amount: int | None = None
    currency: str | None = None
    matching_plan_slugs: list[str] = field(default_factory=list)


@dataclass
class BackfillReport:
    apply: bool
    order_id: str | None = None
    payment_id: str | None = None
    user_id: str | None = None
    plan_slug: str | None = None
    local_payment_id: str | None = None
    local_status: str | None = None
    action: str = "none"  # insert_and_fulfill | fulfill_only | already_paid | dry_run
    inserted: bool = False
    fulfilled: bool = False
    audited: bool = False
    error: str | None = None
    suggest: BackfillSuggest | None = None
    razorpay: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _is_captured_payment(p: dict[str, Any]) -> bool:
    if p.get("captured") is True:
        return True
    return str(p.get("status") or "").lower() == "captured"


def _fetch_razorpay(
    *, order_id: str | None, payment_id: str | None
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """Return (order_id, payment_id, order, payment)."""
    if not razorpay_client.credentials_ready():
        raise BackfillError("Razorpay credentials not ready")
    client = razorpay_client._client()
    order: dict[str, Any] | None = None
    payment: dict[str, Any] | None = None

    if payment_id and not order_id:
        try:
            payment = client.payment.fetch(payment_id)
        except Exception as exc:  # noqa: BLE001
            raise BackfillError(f"Razorpay payment fetch failed: {exc}") from exc
        order_id = str(payment.get("order_id") or "") or None

    if not order_id:
        raise BackfillError("order_id required (or derive from payment_id)")

    try:
        order = client.order.fetch(order_id)
    except Exception as exc:  # noqa: BLE001
        raise BackfillError(
            f"Razorpay order fetch failed (wrong merchant keys?): {exc}"
        ) from exc

    if payment is None:
        if payment_id:
            try:
                payment = client.payment.fetch(payment_id)
            except Exception as exc:  # noqa: BLE001
                raise BackfillError(f"Razorpay payment fetch failed: {exc}") from exc
        else:
            try:
                raw = client.order.payments(order_id)
            except Exception as exc:  # noqa: BLE001
                raise BackfillError(f"Razorpay order.payments failed: {exc}") from exc
            items = raw.get("items") if isinstance(raw, dict) else raw
            captured = [p for p in (items or []) if _is_captured_payment(p)]
            if not captured:
                raise BackfillError("No captured payment found for order")
            payment = captured[0]
            payment_id = str(payment.get("id") or "")

    if not payment_id:
        payment_id = str(payment.get("id") or "")
    if not payment_id:
        raise BackfillError("Could not resolve razorpay payment id")

    order_paid = str((order or {}).get("status") or "") == "paid"
    if not _is_captured_payment(payment) and not order_paid:
        raise BackfillError(
            f"Payment not captured (status={payment.get('status')}, "
            f"order_status={(order or {}).get('status')})"
        )

    return str(order_id), str(payment_id), order or {}, payment


def suggest_from_razorpay(
    *, order_id: str | None, payment_id: str | None
) -> BackfillSuggest:
    _, _, order, payment = _fetch_razorpay(order_id=order_id, payment_id=payment_id)
    amount = payment.get("amount")
    if amount is None:
        amount = order.get("amount")
    currency = str(payment.get("currency") or order.get("currency") or "")
    matching: list[str] = []
    if amount is not None:
        for plan in repository.list_active_plans():
            if int(plan["amount"]) == int(amount) and str(plan.get("currency") or "") == (
                currency or str(plan.get("currency") or "")
            ):
                matching.append(str(plan["slug"]))
            elif int(plan["amount"]) == int(amount):
                matching.append(str(plan["slug"]))
    return BackfillSuggest(
        email=payment.get("email"),
        contact=payment.get("contact"),
        amount=int(amount) if amount is not None else None,
        currency=currency or None,
        matching_plan_slugs=matching,
    )


def _record_audit(
    *,
    order_id: str,
    payment_id: str,
    user_id: UUID,
    plan_slug: str,
    amount: int,
    apply: bool,
    local_payment_id: str | None,
) -> bool:
    event_id = f"backfill:{order_id}"
    row = repository.insert_payment_event(
        razorpay_event_id=event_id,
        event_type=EVENT_BACKFILL,
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_id,
        payload={
            "user_id": str(user_id),
            "plan_slug": plan_slug,
            "order_id": order_id,
            "payment_id": payment_id,
            "local_payment_id": local_payment_id,
            "amount": amount,
            "apply": apply,
            "source": "ops_cli",
        },
        headers={"source": "ops_cli"},
    )
    if row and row.get("id"):
        repository.mark_event_processed(row["id"])
        return True
    return False  # duplicate event id — already audited


def backfill_orphan(
    *,
    order_id: str | None,
    payment_id: str | None,
    user_id: UUID,
    plan_slug: str,
    apply: bool = False,
) -> BackfillReport:
    report = BackfillReport(
        apply=apply,
        user_id=str(user_id),
        plan_slug=plan_slug,
    )
    payment_log(
        "BACKFILL_SCAN",
        order=order_id,
        payment=payment_id,
        user_id=str(user_id),
        plan_slug=plan_slug,
        apply=apply,
    )

    try:
        order_id, payment_id, order, payment = _fetch_razorpay(
            order_id=order_id, payment_id=payment_id
        )
        report.order_id = order_id
        report.payment_id = payment_id
        rzp_amount = int(payment.get("amount") or order.get("amount") or 0)
        rzp_currency = str(payment.get("currency") or order.get("currency") or "")
        report.razorpay = {
            "order_status": order.get("status"),
            "payment_status": payment.get("status"),
            "captured": payment.get("captured"),
            "amount": rzp_amount,
            "currency": rzp_currency,
            "email": payment.get("email"),
            "contact": payment.get("contact"),
        }

        plan = repository.get_plan_by_slug(plan_slug)
        if not plan:
            raise PlanNotFoundError()
        if int(plan["amount"]) != rzp_amount:
            payment_log(
                "BACKFILL_ERROR",
                order=order_id,
                payment=payment_id,
                error="amount_mismatch",
                expected=int(plan["amount"]),
                captured=rzp_amount,
            )
            raise PaymentAmountMismatchError()
        if str(plan.get("currency") or "") != rzp_currency:
            raise BackfillError(
                f"Currency mismatch: plan={plan.get('currency')} razorpay={rzp_currency}"
            )

        local = repository.get_payment_by_order_id(order_id)
        if local:
            report.local_payment_id = str(local["id"])
            report.local_status = str(local["status"])
            if str(local["status"]) == PAYMENT_PAID:
                report.action = "already_paid"
                payment_log(
                    "BACKFILL_SKIPPED",
                    order=order_id,
                    payment=payment_id,
                    reason="already_paid",
                    payment_id=report.local_payment_id,
                )
                if apply:
                    report.audited = _record_audit(
                        order_id=order_id,
                        payment_id=payment_id,
                        user_id=user_id,
                        plan_slug=plan_slug,
                        amount=rzp_amount,
                        apply=apply,
                        local_payment_id=report.local_payment_id,
                    )
                return report

            if str(local["status"]) != PAYMENT_CREATED:
                raise BackfillError(
                    f"Local payment status={local['status']} is not created/paid"
                )

            report.action = "fulfill_only" if apply else "dry_run"
            if not apply:
                payment_log(
                    "BACKFILL_SKIPPED",
                    order=order_id,
                    payment=payment_id,
                    reason="dry_run_fulfill_only",
                    payment_id=report.local_payment_id,
                )
                return report

            service.confirm_payment_paid(
                razorpay_order_id=order_id,
                razorpay_payment_id=payment_id,
                captured_amount=rzp_amount,
                user_id=user_id,
            )
            report.fulfilled = True
            payment_log(
                "BACKFILL_APPLIED",
                order=order_id,
                payment=payment_id,
                payment_id=report.local_payment_id,
                action="fulfill_only",
                success=True,
            )
            report.audited = _record_audit(
                order_id=order_id,
                payment_id=payment_id,
                user_id=user_id,
                plan_slug=plan_slug,
                amount=rzp_amount,
                apply=apply,
                local_payment_id=report.local_payment_id,
            )
            return report

        # Missing local row
        report.action = "insert_and_fulfill" if apply else "dry_run"
        if not apply:
            payment_log(
                "BACKFILL_SKIPPED",
                order=order_id,
                payment=payment_id,
                reason="dry_run_would_insert",
                user_id=str(user_id),
                plan_slug=plan_slug,
                amount=int(plan["amount"]),
            )
            return report

        inserted = repository.insert_payment(
            user_id=user_id,
            plan_id=plan["id"],
            razorpay_order_id=order_id,
            amount=int(plan["amount"]),
            currency=str(plan["currency"]),
        )
        report.inserted = True
        report.local_payment_id = str(inserted.get("id") or "")
        report.local_status = PAYMENT_CREATED
        payment_log(
            "BACKFILL_INSERTED",
            order=order_id,
            payment=payment_id,
            payment_id=report.local_payment_id,
            user_id=str(user_id),
            plan_id=str(plan["id"]),
        )

        service.confirm_payment_paid(
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            captured_amount=rzp_amount,
            user_id=user_id,
        )
        report.fulfilled = True
        payment_log(
            "BACKFILL_APPLIED",
            order=order_id,
            payment=payment_id,
            payment_id=report.local_payment_id,
            action="insert_and_fulfill",
            success=True,
        )
        report.audited = _record_audit(
            order_id=order_id,
            payment_id=payment_id,
            user_id=user_id,
            plan_slug=plan_slug,
            amount=rzp_amount,
            apply=apply,
            local_payment_id=report.local_payment_id,
        )
        return report
    except Exception as exc:
        report.error = str(exc)[:500]
        payment_log(
            "BACKFILL_ERROR",
            order=report.order_id or order_id,
            payment=report.payment_id or payment_id,
            error=report.error,
            success=False,
        )
        raise
