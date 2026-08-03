"""Admin diagnostic funnel — list, detail, speaking review, report email."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    DiagnosticDetail,
    DiagnosticQueueItem,
    DiagnosticQueueResponse,
    DiagnosticSpeakingPart1Item,
    DiagnosticSpeakingSummary,
    DiagnosticWritingSummary,
    HumanCriteriaScores,
    PatchDiagnosticSpeakingRequest,
    SendDiagnosticReportResponse,
)
from app.admin.speaking_band import compute_overall_band, normalize_criteria_scores
from app.db.supabase_client import get_supabase
from app.diagnostic.report_email import send_diagnostic_report_email


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def aggregate_diagnostic_band(
    listening: float | None,
    reading: float | None,
    writing: float | None,
    speaking: float | None,
) -> float | None:
    bands = [b for b in (listening, reading, writing, speaking) if b is not None and b > 0]
    if not bands:
        return None
    return round(sum(bands) / len(bands) * 2) / 2


def _parse_speaking_summary(answers: dict[str, Any] | None) -> DiagnosticSpeakingSummary | None:
    if not answers or not isinstance(answers, dict):
        return None
    speaking = answers.get("speaking")
    if not isinstance(speaking, dict):
        return None

    part1_items: list[DiagnosticSpeakingPart1Item] = []
    part1 = speaking.get("part1")
    if isinstance(part1, dict):
        for qid, rec in part1.items():
            if isinstance(rec, dict):
                part1_items.append(
                    DiagnosticSpeakingPart1Item(
                        question_id=str(qid),
                        duration_sec=int(rec.get("durationSec") or 0),
                        completed=bool(rec.get("completed")),
                    )
                )

    part2 = speaking.get("part2")
    part2_completed = False
    part2_prep: int | None = None
    part2_record: int | None = None
    if isinstance(part2, dict):
        part2_completed = bool(part2.get("completed"))
        part2_prep = int(part2["prepSec"]) if part2.get("prepSec") is not None else None
        part2_record = int(part2["recordSec"]) if part2.get("recordSec") is not None else None

    if not part1_items and not part2_completed:
        return None

    return DiagnosticSpeakingSummary(
        part1=part1_items,
        part2_prep_sec=part2_prep,
        part2_record_sec=part2_record,
        part2_completed=part2_completed,
    )


def _parse_human_criteria(raw: Any) -> HumanCriteriaScores | None:
    normalized = normalize_criteria_scores(raw if isinstance(raw, dict) else None)
    if not normalized:
        return None
    return HumanCriteriaScores.model_validate(normalized)


def _queue_item_from_row(row: dict[str, Any]) -> DiagnosticQueueItem:
    return DiagnosticQueueItem(
        id=UUID(str(row["id"])),
        full_name=str(row.get("full_name") or ""),
        email=row.get("email"),
        phone=str(row.get("phone") or ""),
        goal_label=row.get("goal_label"),
        target_band=_float_or_none(row.get("target_band")),
        listening_band=_float_or_none(row.get("listening_band")),
        reading_band=_float_or_none(row.get("reading_band")),
        writing_band=_float_or_none(row.get("writing_band")),
        speaking_band=_float_or_none(row.get("speaking_band")),
        speaking_human_band=_float_or_none(row.get("speaking_human_band")),
        aggregate_band=_float_or_none(row.get("aggregate_band")),
        status=str(row.get("status") or "pending_review"),
        report_email_sent_at=(
            _parse_dt(row["report_email_sent_at"])
            if row.get("report_email_sent_at")
            else None
        ),
        created_at=_parse_dt(row["created_at"]),
    )


def _count_pending(sb: Any) -> int:
    result = (
        sb.table("diagnostic_review_submissions")
        .select("id", count="exact")
        .eq("status", "pending_review")
        .execute()
    )
    return int(result.count or 0)


def list_diagnostics(
    *,
    status_filter: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> DiagnosticQueueResponse:
    sb = get_supabase()
    query = sb.table("diagnostic_review_submissions").select(
        "id, full_name, email, phone, goal_label, target_band, listening_band, "
        "reading_band, writing_band, speaking_band, speaking_human_band, "
        "aggregate_band, status, report_email_sent_at, created_at",
        count="exact",
    )

    if status_filter and status_filter != "all":
        query = query.eq("status", status_filter)
    else:
        query = query.neq("status", "cancelled")

    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.or_(
            f"full_name.ilike.{pattern},email.ilike.{pattern},phone.ilike.{pattern}"
        )

    offset = max(0, (page - 1) * page_size)
    result = query.order("created_at", desc=True).range(offset, offset + page_size - 1).execute()
    rows = result.data or []
    total = int(result.count or len(rows))

    return DiagnosticQueueResponse(
        items=[_queue_item_from_row(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pending_count=_count_pending(sb),
    )


def _detail_from_row(row: dict[str, Any]) -> DiagnosticDetail:
    eval_row = row.get("diagnostic_ai_evaluations") or {}
    if isinstance(eval_row, list):
        eval_row = eval_row[0] if eval_row else {}
    essay = eval_row.get("essay_text") if isinstance(eval_row, dict) else None
    essay_preview = None
    if isinstance(essay, str) and essay.strip():
        essay_preview = essay.strip()[:280] + ("…" if len(essay.strip()) > 280 else "")

    writing_summary: DiagnosticWritingSummary | None = None
    if isinstance(eval_row, dict) and eval_row:
        feedback = eval_row.get("feedback")
        writing_summary = DiagnosticWritingSummary(
            task_part=int(eval_row["task_part"]) if eval_row.get("task_part") is not None else None,
            overall_band=_float_or_none(eval_row.get("overall_band")),
            essay_preview=essay_preview,
            word_count=int(eval_row["word_count"]) if eval_row.get("word_count") is not None else None,
            ai_feedback=feedback if isinstance(feedback, dict) else None,
        )

    answers = row.get("answers")
    speaking_summary = _parse_speaking_summary(answers if isinstance(answers, dict) else None)

    return DiagnosticDetail(
        id=UUID(str(row["id"])),
        client_attempt_id=str(row.get("client_attempt_id") or ""),
        full_name=str(row.get("full_name") or ""),
        email=row.get("email"),
        phone=str(row.get("phone") or ""),
        goal_label=row.get("goal_label"),
        target_band=_float_or_none(row.get("target_band")),
        listening_band=_float_or_none(row.get("listening_band")),
        reading_band=_float_or_none(row.get("reading_band")),
        writing_band=_float_or_none(row.get("writing_band")),
        writing_human_band=_float_or_none(row.get("human_band")),
        speaking_band=_float_or_none(row.get("speaking_band")),
        speaking_human_band=_float_or_none(row.get("speaking_human_band")),
        aggregate_band=_float_or_none(row.get("aggregate_band")),
        status=str(row.get("status") or "pending_review"),
        speaking_human_criteria_scores=_parse_human_criteria(
            row.get("speaking_human_criteria_scores")
        ),
        speaking_reviewer_notes=row.get("speaking_reviewer_notes"),
        speaking_reviewed_at=(
            _parse_dt(row["speaking_reviewed_at"])
            if row.get("speaking_reviewed_at")
            else None
        ),
        report_email_sent_at=(
            _parse_dt(row["report_email_sent_at"])
            if row.get("report_email_sent_at")
            else None
        ),
        writing_review_id=UUID(str(row["id"])),
        writing=writing_summary,
        speaking=speaking_summary,
        created_at=_parse_dt(row["created_at"]),
        reviewed_at=_parse_dt(row["reviewed_at"]) if row.get("reviewed_at") else None,
    )


def get_diagnostic_detail(diagnostic_id: UUID) -> DiagnosticDetail:
    sb = get_supabase()
    result = (
        sb.table("diagnostic_review_submissions")
        .select(
            "*, diagnostic_ai_evaluations("
            "task_part, question_text, essay_text, word_count, overall_band, feedback)"
        )
        .eq("id", str(diagnostic_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diagnostic submission not found.")
    return _detail_from_row(result.data[0])


def patch_diagnostic_speaking(
    *,
    diagnostic_id: UUID,
    body: PatchDiagnosticSpeakingRequest,
    admin_id: UUID,
) -> DiagnosticDetail:
    sb = get_supabase()
    existing = (
        sb.table("diagnostic_review_submissions")
        .select("id")
        .eq("id", str(diagnostic_id))
        .limit(1)
        .execute()
    ).data
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diagnostic submission not found.")

    scores = body.human_criteria_scores.model_dump()
    speaking_band = compute_overall_band(scores)
    now = datetime.now(UTC).isoformat()

    sb.table("diagnostic_review_submissions").update(
        {
            "speaking_human_band": speaking_band,
            "speaking_human_criteria_scores": scores,
            "speaking_reviewer_notes": body.reviewer_notes,
            "speaking_reviewer_id": str(admin_id),
            "speaking_reviewed_at": now,
        }
    ).eq("id", str(diagnostic_id)).execute()

    log_admin_action(
        admin_id=admin_id,
        action="diagnostic.speaking.approve",
        resource_type="diagnostic_review_submission",
        resource_id=diagnostic_id,
        metadata={"speaking_human_band": speaking_band},
    )

    return get_diagnostic_detail(diagnostic_id)


async def send_diagnostic_report(
    *,
    diagnostic_id: UUID,
    admin_id: UUID,
) -> SendDiagnosticReportResponse:
    sb = get_supabase()
    result = (
        sb.table("diagnostic_review_submissions")
        .select("*, diagnostic_ai_evaluations(task_part, overall_band, feedback)")
        .eq("id", str(diagnostic_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diagnostic submission not found.")
    row = result.data[0]

    email = (row.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Student email is required to send the report.",
        )

    speaking_human = _float_or_none(row.get("speaking_human_band"))
    if speaking_human is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Speaking must be scored before sending the report.",
        )

    writing_band = _float_or_none(row.get("human_band")) or _float_or_none(
        row.get("writing_band")
    )
    if writing_band is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Writing band is required before sending the report.",
        )

    listening = _float_or_none(row.get("listening_band"))
    reading = _float_or_none(row.get("reading_band"))
    aggregate = aggregate_diagnostic_band(listening, reading, writing_band, speaking_human)

    eval_row = row.get("diagnostic_ai_evaluations") or {}
    if isinstance(eval_row, list):
        eval_row = eval_row[0] if eval_row else {}
    feedback = eval_row.get("feedback") if isinstance(eval_row, dict) else None

    sent_ok = await send_diagnostic_report_email(
        to=email,
        name=str(row.get("full_name") or ""),
        goal_label=row.get("goal_label"),
        target_band=_float_or_none(row.get("target_band")),
        listening_band=listening,
        reading_band=reading,
        writing_band=writing_band,
        speaking_band=speaking_human,
        aggregate_band=aggregate,
        writing_feedback=feedback if isinstance(feedback, dict) else None,
        speaking_notes=row.get("speaking_reviewer_notes"),
    )
    if not sent_ok:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not send report email. Check Resend configuration.",
        )

    now = datetime.now(UTC)
    sb.table("diagnostic_review_submissions").update(
        {
            "report_email_sent_at": now.isoformat(),
            "report_email_sent_by": str(admin_id),
        }
    ).eq("id", str(diagnostic_id)).execute()

    log_admin_action(
        admin_id=admin_id,
        action="diagnostic.report.send",
        resource_type="diagnostic_review_submission",
        resource_id=diagnostic_id,
        metadata={"recipient": email, "aggregate_band": aggregate},
    )

    return SendDiagnosticReportResponse(ok=True, sent_at=now, recipient=email)
