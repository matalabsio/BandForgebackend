"""Submit diagnostic for human examiner review."""

from __future__ import annotations

import logging
from typing import Any

from app.db.supabase_client import get_supabase
from app.diagnostic.review_email import send_diagnostic_submitted_email
from app.diagnostic.schemas import DiagnosticReviewSubmitRequest, DiagnosticReviewSubmitResponse

logger = logging.getLogger(__name__)


def _lookup_writing_evaluation(client_attempt_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("diagnostic_ai_evaluations")
        .select("id, overall_band")
        .eq("client_attempt_id", client_attempt_id)
        .eq("evaluation_type", "writing")
        .maybe_single()
        .execute()
    )
    row = getattr(result, "data", None)
    return row if isinstance(row, dict) else None


async def submit_diagnostic_review(
    body: DiagnosticReviewSubmitRequest,
) -> DiagnosticReviewSubmitResponse:
    sb = get_supabase()

    # Writing AI evaluation is optional: a too-short / empty essay skips AI
    # scoring (writing band stays null) but the diagnostic must still be queued
    # for human review so it shows up in the admin Diagnostics queue.
    writing_eval = _lookup_writing_evaluation(body.client_attempt_id)
    writing_band = (
        float(writing_eval["overall_band"])
        if writing_eval and writing_eval.get("overall_band") is not None
        else body.writing_band
    )

    payload: dict[str, Any] = {
        "client_attempt_id": body.client_attempt_id,
        "full_name": body.full_name.strip(),
        "phone": body.phone.strip(),
        "email": body.email.strip().lower() if body.email else None,
        "goal_label": body.goal_label,
        "target_band": body.target_band,
        "listening_band": body.listening_band,
        "reading_band": body.reading_band,
        "writing_band": writing_band,
        "speaking_band": body.speaking_band,
        "aggregate_band": body.aggregate_band,
        "answers": body.answers,
        "review": body.review,
        "status": "pending_review",
    }
    if writing_eval and writing_eval.get("id"):
        payload["writing_evaluation_id"] = str(writing_eval["id"])

    existing = (
        sb.table("diagnostic_review_submissions")
        .select("id")
        .eq("client_attempt_id", body.client_attempt_id)
        .maybe_single()
        .execute()
    )
    row = getattr(existing, "data", None)

    if row and row.get("id"):
        row_id = str(row["id"])
        sb.table("diagnostic_review_submissions").update(payload).eq("id", row_id).execute()
    else:
        inserted = sb.table("diagnostic_review_submissions").insert(payload).execute()
        rows = inserted.data or []
        if not rows:
            raise RuntimeError("Could not save diagnostic review submission.")
        row_id = str(rows[0]["id"])

    if body.email:
        try:
            await send_diagnostic_submitted_email(
                to=body.email.strip().lower(),
                name=body.full_name.strip(),
            )
        except Exception:
            logger.exception("Failed to send diagnostic confirmation email")

    return DiagnosticReviewSubmitResponse(
        id=row_id,
        client_attempt_id=body.client_attempt_id,
        status="pending_review",
    )
