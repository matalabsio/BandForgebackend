"""Admin speaking review queue."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    ApproveSpeakingRequest,
    HumanCriteriaScores,
    PatchSpeakingReviewRequest,
    SpeakingQueueItem,
    SpeakingQueueResponse,
    SpeakingReviewDetail,
    SpeakingSubmissionMeta,
)
from app.admin.speaking_band import (
    ai_scores_to_criteria,
    compute_overall_band,
    normalize_criteria_scores,
)
from app.db.supabase_client import get_supabase
from app.services import user_activity
from app.storage.r2 import generate_signed_url


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _count_pending(sb: Any) -> int:
    result = (
        sb.table("speaking_reviews")
        .select("id", count="exact")
        .eq("status", "pending")
        .execute()
    )
    return int(result.count or 0)


def _ai_overall_band(ai_scores: dict[str, Any] | None) -> float | None:
    criteria = ai_scores_to_criteria(ai_scores)
    if not criteria:
        return None
    try:
        return compute_overall_band(criteria)
    except ValueError:
        return None


def _parse_submission_meta(raw: Any) -> SpeakingSubmissionMeta | None:
    if not raw or not isinstance(raw, dict):
        return None
    return SpeakingSubmissionMeta.model_validate(raw)


def _parse_human_criteria(raw: Any) -> HumanCriteriaScores | None:
    normalized = normalize_criteria_scores(raw if isinstance(raw, dict) else None)
    if not normalized:
        return None
    return HumanCriteriaScores.model_validate(normalized)


def _student_context(user_id: str | None) -> tuple[float | None, float | None]:
    if not user_id:
        return None, None
    try:
        stats = user_activity.build_user_activity_stats(UUID(str(user_id)))
        return stats.get("best_band"), None
    except Exception:
        return None, None


def _student_name(user: dict[str, Any], submission_meta: Any) -> str | None:
    name = user.get("full_name")
    if name:
        return str(name)
    if isinstance(submission_meta, dict):
        display = submission_meta.get("student_display_name")
        if display:
            return str(display)
    return None


def _detail_from_row(sb: Any, row: dict[str, Any]) -> SpeakingReviewDetail:
    attempt = row.get("test_attempts") or {}
    user = attempt.get("users") or {}
    user_id = attempt.get("user_id")

    audio_play_url: str | None = None
    audio_key = row.get("audio_url")
    if audio_key:
        try:
            audio_play_url = generate_signed_url(str(audio_key))
        except Exception:
            audio_play_url = None

    target_raw = user.get("target_band")
    student_target = float(target_raw) if target_raw is not None else None
    student_current, _ = _student_context(str(user_id) if user_id else None)

    return SpeakingReviewDetail(
        id=UUID(str(row["id"])),
        attempt_id=UUID(str(row["attempt_id"])),
        status=str(row["status"]),
        human_band=(
            float(row["human_band"]) if row.get("human_band") is not None else None
        ),
        human_criteria_scores=_parse_human_criteria(row.get("human_criteria_scores")),
        submission_meta=_parse_submission_meta(row.get("submission_meta")),
        reviewer_notes=row.get("reviewer_notes"),
        transcript=row.get("transcript"),
        audio_url=row.get("audio_url"),
        audio_play_url=audio_play_url,
        ai_scores=row.get("ai_scores"),
        student_name=_student_name(user, row.get("submission_meta")),
        student_email=user.get("email"),
        student_target_band=student_target,
        student_current_band=student_current,
        queue_pending_count=_count_pending(sb),
        created_at=_parse_dt(row["created_at"]),
        reviewed_at=(
            _parse_dt(row["reviewed_at"]) if row.get("reviewed_at") else None
        ),
    )


def list_speaking_queue(
    *,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> SpeakingQueueResponse:
    sb = get_supabase()
    query = sb.table("speaking_reviews").select(
        "id, attempt_id, status, human_band, ai_scores, created_at, test_attempts(user_id, users(full_name, email))",
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
    total = result.count or len(rows)
    pending_count = _count_pending(sb)

    items: list[SpeakingQueueItem] = []
    for row in rows:
        attempt = row.get("test_attempts") or {}
        user = attempt.get("users") or {}
        items.append(
            SpeakingQueueItem(
                id=UUID(str(row["id"])),
                attempt_id=UUID(str(row["attempt_id"])),
                student_name=_student_name(user, row.get("submission_meta")),
                student_email=user.get("email"),
                status=str(row["status"]),
                human_band=(
                    float(row["human_band"]) if row.get("human_band") is not None else None
                ),
                ai_overall_band=_ai_overall_band(row.get("ai_scores")),
                created_at=_parse_dt(row["created_at"]),
            )
        )

    return SpeakingQueueResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pending_count=pending_count,
    )


def get_speaking_detail(review_id: UUID) -> SpeakingReviewDetail:
    sb = get_supabase()
    result = (
        sb.table("speaking_reviews")
        .select(
            "*, test_attempts(user_id, users(full_name, email, target_band))"
        )
        .eq("id", str(review_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    return _detail_from_row(sb, result.data[0])


def patch_speaking_review(
    *,
    review_id: UUID,
    body: PatchSpeakingReviewRequest,
    admin_id: UUID,
) -> SpeakingReviewDetail:
    sb = get_supabase()
    existing = (
        sb.table("speaking_reviews")
        .select("id, status")
        .eq("id", str(review_id))
        .limit(1)
        .execute()
    ).data
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    if str(existing[0].get("status")) == "completed":
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

    sb.table("speaking_reviews").update(patch).eq("id", str(review_id)).execute()

    log_admin_action(
        admin_id=admin_id,
        action="speaking.draft",
        resource_type="speaking_review",
        resource_id=review_id,
        metadata={"status": patch.get("status", "unchanged")},
    )

    return get_speaking_detail(review_id)


def approve_speaking_review(
    *,
    review_id: UUID,
    body: ApproveSpeakingRequest,
    admin_id: UUID,
) -> SpeakingReviewDetail:
    sb = get_supabase()
    existing = (
        sb.table("speaking_reviews")
        .select("id, status, ai_scores")
        .eq("id", str(review_id))
        .limit(1)
        .execute()
    ).data
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    if str(existing[0].get("status")) == "completed":
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

    sb.table("speaking_reviews").update(
        {
            "status": "completed",
            "human_band": human_band,
            "human_criteria_scores": scores,
            "reviewer_notes": body.reviewer_notes,
            "reviewer_id": str(admin_id),
            "reviewed_at": now,
        }
    ).eq("id", str(review_id)).execute()

    review_row = (
        sb.table("speaking_reviews")
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
                    "module": "speaking",
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
        action="speaking.approve",
        resource_type="speaking_review",
        resource_id=review_id,
        metadata=approve_audit_metadata(
            human_band=human_band,
            human_criteria=scores,
            ai_band=ai_band,
            ai_criteria=ai_criteria,
        ),
    )

    return get_speaking_detail(review_id)
