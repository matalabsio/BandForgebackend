"""Admin writing review queue (mock tests + diagnostic funnel)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    ApproveWritingRequest,
    PatchWritingReviewRequest,
    WritingHumanCriteriaScores,
    WritingQueueItem,
    WritingQueueResponse,
    WritingReviewDetail,
    WritingSubmissionMeta,
)
from app.admin.writing_band import (
    ai_scores_to_criteria,
    compute_overall_band,
    normalize_criteria_scores,
)
from app.db.supabase_client import get_supabase
from app.services import user_activity


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _normalize_mock_status(status: str) -> str:
    return status


def _normalize_diagnostic_status(status: str) -> str:
    if status == "pending_review":
        return "pending"
    if status == "reviewed":
        return "completed"
    return status


def _diagnostic_db_status(filter_status: str | None) -> str | None:
    if not filter_status:
        return None
    if filter_status == "pending":
        return "pending_review"
    if filter_status == "completed":
        return "reviewed"
    return filter_status


def _count_pending(sb: Any) -> int:
    mock_pending = (
        sb.table("writing_reviews")
        .select("id", count="exact")
        .eq("status", "pending")
        .execute()
    ).count or 0
    diag_pending = (
        sb.table("diagnostic_review_submissions")
        .select("id", count="exact")
        .eq("status", "pending_review")
        .execute()
    ).count or 0
    return int(mock_pending) + int(diag_pending)


def _ai_status_label(ai_scores: dict[str, Any] | None) -> str | None:
    if not isinstance(ai_scores, dict) or not ai_scores.get("status"):
        return None
    return str(ai_scores["status"])


def _ai_error_message(ai_scores: dict[str, Any] | None) -> str | None:
    if not isinstance(ai_scores, dict) or not ai_scores.get("error"):
        return None
    return str(ai_scores["error"])


def _ai_overall_band(ai_scores: dict[str, Any] | None) -> float | None:
    if not ai_scores:
        return None
    status = ai_scores.get("status")
    # Prefer persisted AI band once evaluation finished.
    if status in ("ai_complete", "ai_stub") and ai_scores.get("ai_band") is not None:
        try:
            return float(ai_scores["ai_band"])
        except (TypeError, ValueError):
            pass
    criteria = ai_scores_to_criteria(ai_scores)
    if criteria:
        try:
            return compute_overall_band(criteria)
        except ValueError:
            pass
    # Only fall back to word-count estimate when AI has not completed yet.
    if status not in ("ai_complete", "ai_stub"):
        estimate = ai_scores.get("word_count_estimate")
        if estimate is not None:
            try:
                return float(estimate)
            except (TypeError, ValueError):
                return None
    return None


def _parse_submission_meta(raw: Any) -> WritingSubmissionMeta | None:
    if not raw or not isinstance(raw, dict):
        return None
    return WritingSubmissionMeta.model_validate(raw)


def _parse_human_criteria(raw: Any) -> WritingHumanCriteriaScores | None:
    normalized = normalize_criteria_scores(raw if isinstance(raw, dict) else None)
    if not normalized:
        return None
    return WritingHumanCriteriaScores.model_validate(normalized)


def _student_context(user_id: str | None) -> tuple[float | None, float | None]:
    if not user_id:
        return None, None
    try:
        stats = user_activity.build_user_activity_stats(UUID(str(user_id)))
        return stats.get("best_band"), None
    except Exception:
        return None, None


def _mock_task_label(meta: WritingSubmissionMeta | None) -> str | None:
    if not meta:
        return None
    if meta.part_label:
        return meta.part_label
    if meta.part is not None:
        return f"Task {meta.part}"
    return None


def _mock_queue_rows(
    sb: Any,
    *,
    status_filter: str | None,
) -> list[WritingQueueItem]:
    query = sb.table("writing_reviews").select(
        "id, status, human_band, ai_scores, submission_meta, created_at, "
        "test_attempts(user_id, users(full_name, email))"
    )
    if status_filter:
        query = query.eq("status", status_filter)
    rows = query.order("created_at", desc=True).execute().data or []
    items: list[WritingQueueItem] = []
    for row in rows:
        attempt = row.get("test_attempts") or {}
        user = attempt.get("users") or {}
        meta = _parse_submission_meta(row.get("submission_meta"))
        items.append(
            WritingQueueItem(
                id=UUID(str(row["id"])),
                source="mock",
                student_name=user.get("full_name"),
                student_email=user.get("email"),
                status=_normalize_mock_status(str(row["status"])),
                human_band=(
                    float(row["human_band"]) if row.get("human_band") is not None else None
                ),
                ai_overall_band=_ai_overall_band(row.get("ai_scores")),
                ai_status=_ai_status_label(
                    row.get("ai_scores") if isinstance(row.get("ai_scores"), dict) else None
                ),
                task_label=_mock_task_label(meta),
                created_at=_parse_dt(row["created_at"]),
            )
        )
    return items


def _diagnostic_queue_rows(
    sb: Any,
    *,
    status_filter: str | None,
) -> list[WritingQueueItem]:
    db_status = _diagnostic_db_status(status_filter)
    query = sb.table("diagnostic_review_submissions").select(
        "id, full_name, email, status, human_band, writing_band, created_at, "
        "writing_evaluation_id, diagnostic_ai_evaluations(task_part, overall_band)"
    )
    if db_status:
        query = query.eq("status", db_status)
    else:
        query = query.neq("status", "cancelled")
    rows = query.order("created_at", desc=True).execute().data or []
    items: list[WritingQueueItem] = []
    for row in rows:
        eval_row = row.get("diagnostic_ai_evaluations") or {}
        task_part = int(eval_row.get("task_part") or 1)
        ai_band = row.get("writing_band")
        if ai_band is None and eval_row.get("overall_band") is not None:
            ai_band = eval_row.get("overall_band")
        items.append(
            WritingQueueItem(
                id=UUID(str(row["id"])),
                source="diagnostic",
                student_name=row.get("full_name"),
                student_email=row.get("email"),
                status=_normalize_diagnostic_status(str(row["status"])),
                human_band=(
                    float(row["human_band"]) if row.get("human_band") is not None else None
                ),
                ai_overall_band=float(ai_band) if ai_band is not None else None,
                task_label=f"Diagnostic · Task {task_part}",
                created_at=_parse_dt(row["created_at"]),
            )
        )
    return items


def list_writing_queue(
    *,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> WritingQueueResponse:
    sb = get_supabase()
    merged = _mock_queue_rows(sb, status_filter=status_filter) + _diagnostic_queue_rows(
        sb, status_filter=status_filter
    )
    merged.sort(key=lambda item: item.created_at, reverse=True)
    total = len(merged)
    offset = max(0, (page - 1) * page_size)
    items = merged[offset : offset + page_size]
    return WritingQueueResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pending_count=_count_pending(sb),
    )


def _mock_detail(sb: Any, review_id: UUID) -> WritingReviewDetail:
    result = (
        sb.table("writing_reviews")
        .select(
            "*, test_attempts(user_id, mock_test_id, users(full_name, email, target_band), "
            "mock_tests(title))"
        )
        .eq("id", str(review_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    row = result.data[0]
    attempt = row.get("test_attempts") or {}
    user = attempt.get("users") or {}
    mock = attempt.get("mock_tests") or {}
    user_id = attempt.get("user_id")
    meta = _parse_submission_meta(row.get("submission_meta"))
    target_raw = user.get("target_band")
    student_target = float(target_raw) if target_raw is not None else None
    student_current, _ = _student_context(str(user_id) if user_id else None)
    essay = meta.essay if meta else None
    question = meta.question if meta else None
    word_count = meta.word_count if meta else None
    return WritingReviewDetail(
        id=UUID(str(row["id"])),
        source="mock",
        attempt_id=UUID(str(row["attempt_id"])),
        status=str(row["status"]),
        human_band=(
            float(row["human_band"]) if row.get("human_band") is not None else None
        ),
        human_criteria_scores=_parse_human_criteria(row.get("human_criteria_scores")),
        submission_meta=meta,
        essay=essay,
        question=question,
        word_count=word_count,
        reviewer_notes=row.get("reviewer_notes"),
        ai_scores=row.get("ai_scores"),
        ai_feedback=None,
        ai_status=_ai_status_label(
            row.get("ai_scores") if isinstance(row.get("ai_scores"), dict) else None
        ),
        ai_error=_ai_error_message(
            row.get("ai_scores") if isinstance(row.get("ai_scores"), dict) else None
        ),
        student_name=user.get("full_name"),
        student_email=user.get("email"),
        student_target_band=student_target,
        student_current_band=student_current,
        task_label=_mock_task_label(meta),
        mock_title=mock.get("title") or (meta.mock_title if meta else None),
        queue_pending_count=_count_pending(sb),
        created_at=_parse_dt(row["created_at"]),
        reviewed_at=(
            _parse_dt(row["reviewed_at"]) if row.get("reviewed_at") else None
        ),
    )


def _diagnostic_detail(sb: Any, review_id: UUID) -> WritingReviewDetail:
    result = (
        sb.table("diagnostic_review_submissions")
        .select(
            "*, diagnostic_ai_evaluations("
            "task_part, question_text, essay_text, word_count, overall_band, "
            "criteria_scores, feedback)"
        )
        .eq("id", str(review_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    row = result.data[0]
    eval_row = row.get("diagnostic_ai_evaluations") or {}
    task_part = int(eval_row.get("task_part") or 1)
    criteria_scores = eval_row.get("criteria_scores") or {}
    ai_scores = criteria_scores if isinstance(criteria_scores, dict) else {}
    if eval_row.get("overall_band") is not None:
        ai_scores = {**ai_scores, "overall_band": eval_row.get("overall_band")}
    target_raw = row.get("target_band")
    return WritingReviewDetail(
        id=UUID(str(row["id"])),
        source="diagnostic",
        client_attempt_id=row.get("client_attempt_id"),
        status=_normalize_diagnostic_status(str(row["status"])),
        human_band=(
            float(row["human_band"]) if row.get("human_band") is not None else None
        ),
        human_criteria_scores=_parse_human_criteria(row.get("human_criteria_scores")),
        submission_meta=None,
        essay=eval_row.get("essay_text"),
        question=eval_row.get("question_text"),
        word_count=int(eval_row.get("word_count") or 0) or None,
        reviewer_notes=row.get("reviewer_notes"),
        ai_scores=ai_scores,
        ai_feedback=eval_row.get("feedback") if isinstance(eval_row.get("feedback"), dict) else None,
        ai_status="ai_complete" if ai_scores else None,
        ai_error=None,
        student_name=row.get("full_name"),
        student_email=row.get("email"),
        student_target_band=float(target_raw) if target_raw is not None else None,
        student_current_band=None,
        task_label=f"Diagnostic · Task {task_part}",
        mock_title=None,
        queue_pending_count=_count_pending(sb),
        created_at=_parse_dt(row["created_at"]),
        reviewed_at=(
            _parse_dt(row["reviewed_at"]) if row.get("reviewed_at") else None
        ),
    )


def get_writing_detail(*, review_id: UUID, source: Literal["mock", "diagnostic"]) -> WritingReviewDetail:
    sb = get_supabase()
    if source == "mock":
        return _mock_detail(sb, review_id)
    return _diagnostic_detail(sb, review_id)


def patch_writing_review(
    *,
    review_id: UUID,
    source: Literal["mock", "diagnostic"],
    body: PatchWritingReviewRequest,
    admin_id: UUID,
) -> WritingReviewDetail:
    sb = get_supabase()
    table = "writing_reviews" if source == "mock" else "diagnostic_review_submissions"
    existing = (
        sb.table(table).select("id, status").eq("id", str(review_id)).limit(1).execute()
    ).data
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    current_status = str(existing[0].get("status"))
    if current_status in ("completed", "reviewed"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Completed reviews cannot be edited.",
        )

    patch: dict[str, Any] = {"reviewer_id": str(admin_id)}
    if body.reviewer_notes is not None:
        patch["reviewer_notes"] = body.reviewer_notes
    if body.human_criteria_scores is not None:
        scores = body.human_criteria_scores.model_dump()
        patch["human_criteria_scores"] = scores
        patch["human_band"] = compute_overall_band(scores)
    if body.status == "in_review":
        patch["status"] = "in_review"

    sb.table(table).update(patch).eq("id", str(review_id)).execute()

    log_admin_action(
        admin_id=admin_id,
        action="writing.draft",
        resource_type="writing_review",
        resource_id=review_id,
        metadata={"source": source, "status": patch.get("status", "unchanged")},
    )

    return get_writing_detail(review_id=review_id, source=source)


def approve_writing_review(
    *,
    review_id: UUID,
    source: Literal["mock", "diagnostic"],
    body: ApproveWritingRequest,
    admin_id: UUID,
) -> WritingReviewDetail:
    sb = get_supabase()
    table = "writing_reviews" if source == "mock" else "diagnostic_review_submissions"
    existing = (
        sb.table(table)
        .select("id, status, ai_scores")
        .eq("id", str(review_id))
        .limit(1)
        .execute()
    ).data
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    current_status = str(existing[0].get("status"))
    if current_status in ("completed", "reviewed"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Review is already completed.",
        )

    scores = body.human_criteria_scores.model_dump()
    human_band = compute_overall_band(scores)
    raw_ai = existing[0].get("ai_scores")
    ai_scores = raw_ai if isinstance(raw_ai, dict) else None
    ai_criteria = ai_scores_to_criteria(ai_scores)
    ai_band = compute_overall_band(ai_criteria) if ai_criteria else None
    now = datetime.now(UTC).isoformat()
    final_status = "completed" if source == "mock" else "reviewed"

    sb.table(table).update(
        {
            "status": final_status,
            "human_band": human_band,
            "human_criteria_scores": scores,
            "reviewer_notes": body.reviewer_notes,
            "reviewer_id": str(admin_id),
            "reviewed_at": now,
        }
    ).eq("id", str(review_id)).execute()

    if source == "mock":
        review_row = (
            sb.table("writing_reviews")
            .select("attempt_id")
            .eq("id", str(review_id))
            .limit(1)
            .execute()
        ).data
        if review_row:
            attempt_id = review_row[0].get("attempt_id")
            if attempt_id:
                sb.table("module_scores").upsert(
                    {
                        "attempt_id": str(attempt_id),
                        "module": "writing",
                        "band": human_band,
                        "raw_score": None,
                        "correct_count": None,
                        "total_count": None,
                        "skill_breakdown": scores,
                    },
                    on_conflict="attempt_id,module",
                ).execute()

                attempt_row = (
                    sb.table("test_attempts")
                    .select("user_id, mock_attempt_id, mock_test_id")
                    .eq("id", str(attempt_id))
                    .limit(1)
                    .execute()
                ).data
                if attempt_row:
                    from uuid import UUID as PyUUID

                    from app.cache.hybrid_cache import delete_many
                    from app.cache.mock_cache import (
                        invalidate_mock_history_caches,
                        invalidate_mock_progress_caches,
                    )

                    user_id = PyUUID(str(attempt_row[0]["user_id"]))
                    delete_many([f"dashboard_summary:{user_id}"])
                    try:
                        from app.learning.service import schedule_profile_refresh

                        schedule_profile_refresh(user_id)
                    except Exception:
                        pass
                    mock_attempt_raw = attempt_row[0].get("mock_attempt_id")
                    mock_test_raw = attempt_row[0].get("mock_test_id")
                    if mock_attempt_raw and mock_test_raw:
                        mock_attempt_id = PyUUID(str(mock_attempt_raw))
                        mock_test_id = PyUUID(str(mock_test_raw))
                        invalidate_mock_progress_caches(
                            user_id=user_id,
                            mock_test_id=mock_test_id,
                            mock_attempt_id=mock_attempt_id,
                        )
                        invalidate_mock_history_caches(
                            user_id=user_id,
                            mock_test_id=mock_test_id,
                        )

    from app.admin.review_comparison import approve_audit_metadata

    log_admin_action(
        admin_id=admin_id,
        action="writing.approve",
        resource_type="writing_review",
        resource_id=review_id,
        metadata=approve_audit_metadata(
            human_band=human_band,
            human_criteria=scores,
            ai_band=ai_band,
            ai_criteria=ai_criteria,
            extra={"source": source},
        ),
    )

    return get_writing_detail(review_id=review_id, source=source)


def retry_writing_ai_evaluation(
    *,
    review_id: UUID,
    source: Literal["mock", "diagnostic"],
    admin_id: UUID,
) -> WritingReviewDetail:
    """Re-enqueue mock writing AI eval for pending/failed rows."""
    if source != "mock":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="AI retry is only available for mock writing reviews.",
        )
    sb = get_supabase()
    existing = (
        sb.table("writing_reviews")
        .select("id, ai_scores")
        .eq("id", str(review_id))
        .limit(1)
        .execute()
    ).data
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")

    raw_ai = existing[0].get("ai_scores")
    ai_scores = raw_ai if isinstance(raw_ai, dict) else {}
    status_label = str(ai_scores.get("status") or "")
    if status_label in ("ai_complete", "ai_stub"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="AI evaluation already completed for this review.",
        )

    from app.writing.ai_evaluator import AI_STATUS_PENDING, run_writing_evaluation

    merged = {**ai_scores, "status": AI_STATUS_PENDING, "error": None}
    sb.table("writing_reviews").update({"ai_scores": merged}).eq(
        "id", str(review_id)
    ).execute()
    run_writing_evaluation(review_id)

    log_admin_action(
        admin_id=admin_id,
        action="writing.ai_retry",
        resource_type="writing_review",
        resource_id=review_id,
        metadata={"previous_status": status_label or None},
    )
    return get_writing_detail(review_id=review_id, source=source)
