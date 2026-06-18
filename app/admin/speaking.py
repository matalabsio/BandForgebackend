"""Admin speaking review queue."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    ApproveSpeakingRequest,
    SpeakingQueueItem,
    SpeakingQueueResponse,
    SpeakingReviewDetail,
)
from app.db.supabase_client import get_supabase
from app.storage.r2 import generate_signed_url


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def list_speaking_queue(
    *,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> SpeakingQueueResponse:
    sb = get_supabase()
    query = sb.table("speaking_reviews").select(
        "id, attempt_id, status, human_band, created_at, test_attempts(user_id, users(full_name, email))",
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

    items: list[SpeakingQueueItem] = []
    for row in rows:
        attempt = row.get("test_attempts") or {}
        user = attempt.get("users") or {}
        items.append(
            SpeakingQueueItem(
                id=UUID(str(row["id"])),
                attempt_id=UUID(str(row["attempt_id"])),
                student_name=user.get("full_name"),
                student_email=user.get("email"),
                status=str(row["status"]),
                human_band=(
                    float(row["human_band"]) if row.get("human_band") is not None else None
                ),
                created_at=_parse_dt(row["created_at"]),
            )
        )

    return SpeakingQueueResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


def get_speaking_detail(review_id: UUID) -> SpeakingReviewDetail:
    sb = get_supabase()
    result = (
        sb.table("speaking_reviews")
        .select(
            "*, test_attempts(user_id, users(full_name, email))"
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

    audio_play_url: str | None = None
    audio_key = row.get("audio_url")
    if audio_key:
        try:
            audio_play_url = generate_signed_url(str(audio_key))
        except Exception:
            audio_play_url = None

    return SpeakingReviewDetail(
        id=UUID(str(row["id"])),
        attempt_id=UUID(str(row["attempt_id"])),
        status=str(row["status"]),
        human_band=(
            float(row["human_band"]) if row.get("human_band") is not None else None
        ),
        reviewer_notes=row.get("reviewer_notes"),
        transcript=row.get("transcript"),
        audio_url=row.get("audio_url"),
        audio_play_url=audio_play_url,
        ai_scores=row.get("ai_scores"),
        student_name=user.get("full_name"),
        student_email=user.get("email"),
        created_at=_parse_dt(row["created_at"]),
        reviewed_at=(
            _parse_dt(row["reviewed_at"]) if row.get("reviewed_at") else None
        ),
    )


def approve_speaking_review(
    *,
    review_id: UUID,
    body: ApproveSpeakingRequest,
    admin_id: UUID,
) -> SpeakingReviewDetail:
    sb = get_supabase()
    now = datetime.now(UTC).isoformat()
    sb.table("speaking_reviews").update(
        {
            "status": "completed",
            "human_band": body.human_band,
            "reviewer_notes": body.reviewer_notes,
            "reviewer_id": str(admin_id),
            "reviewed_at": now,
        }
    ).eq("id", str(review_id)).execute()

    log_admin_action(
        admin_id=admin_id,
        action="speaking.approve",
        resource_type="speaking_review",
        resource_id=review_id,
        metadata={"human_band": body.human_band},
    )

    return get_speaking_detail(review_id)
