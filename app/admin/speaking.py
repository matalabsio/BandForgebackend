"""Admin speaking review queue."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.admin.schemas import (
    ApproveSpeakingRequest,
    HumanCriteriaScores,
    PatchSpeakingReviewRequest,
    ReopenSpeakingReviewRequest,
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


def _approval_request_hash(body: ApproveSpeakingRequest) -> str:
    payload = body.model_dump(mode="json", exclude={"idempotency_key"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _invalidate_speaking_result_caches(sb: Any, attempt_id: Any) -> None:
    attempt_row = (
        sb.table("test_attempts")
        .select("user_id, mock_attempt_id, mock_test_id")
        .eq("id", str(attempt_id))
        .limit(1)
        .execute()
    ).data
    if not attempt_row:
        return

    from app.cache.hybrid_cache import delete_many
    from app.cache.mock_cache import (
        invalidate_mock_history_caches,
        invalidate_mock_progress_caches,
    )

    user_id = UUID(str(attempt_row[0]["user_id"]))
    delete_many([f"dashboard_summary:{user_id}"])
    try:
        from app.learning.service import schedule_profile_refresh

        schedule_profile_refresh(user_id)
    except Exception:
        pass
    mock_attempt_raw = attempt_row[0].get("mock_attempt_id")
    mock_test_raw = attempt_row[0].get("mock_test_id")
    if mock_attempt_raw and mock_test_raw:
        mock_attempt_id = UUID(str(mock_attempt_raw))
        mock_test_id = UUID(str(mock_test_raw))
        invalidate_mock_progress_caches(
            user_id=user_id,
            mock_test_id=mock_test_id,
            mock_attempt_id=mock_attempt_id,
        )
        invalidate_mock_history_caches(
            user_id=user_id,
            mock_test_id=mock_test_id,
        )


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
    enriched = dict(raw)
    responses = raw.get("responses")
    if isinstance(responses, list):
        enriched_responses: list[dict[str, Any]] = []
        for item in responses:
            if not isinstance(item, dict):
                continue
            response = dict(item)
            audio_key = response.get("audio_url")
            if audio_key:
                try:
                    response["audio_play_url"] = generate_signed_url(str(audio_key))
                except Exception:
                    response["audio_play_url"] = None
            enriched_responses.append(response)
        enriched["responses"] = enriched_responses
    return SpeakingSubmissionMeta.model_validate(enriched)


def _parse_human_criteria(raw: Any) -> HumanCriteriaScores | None:
    normalized = normalize_criteria_scores(raw if isinstance(raw, dict) else None)
    if not normalized:
        return None
    return HumanCriteriaScores.model_validate(normalized)


def _admin_evidence(evaluation: Any) -> list[dict[str, Any]]:
    if not isinstance(evaluation, dict):
        return []
    raw = evaluation.get("evidence_quotes")
    confidence = (
        evaluation.get("band_scores", {}).get("P_confidence")
        if isinstance(evaluation.get("band_scores"), dict)
        else None
    )
    evidence: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        enriched = dict(item)
        if enriched.get("criterion") == "P":
            enriched.update(
                {
                    "advisory_only": True,
                    "inference_source": "transcript_inferred",
                    "confidence": confidence,
                }
            )
        evidence.append(enriched)
    return evidence


def _admin_pronunciation_advisory(evaluation: Any) -> dict[str, Any] | None:
    if not isinstance(evaluation, dict):
        return None
    band_scores = evaluation.get("band_scores")
    confidence = (
        band_scores.get("P_confidence") if isinstance(band_scores, dict) else None
    )
    try:
        parsed_confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        parsed_confidence = None
    return {
        "inference_source": "transcript_inferred",
        "advisory_only": True,
        "confidence": parsed_confidence,
        "low_confidence": parsed_confidence is None or parsed_confidence < 0.7,
        "released_score_authority": "human_examiner",
    }


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


def _hydrate_response_meta(sb: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Use live response rows; retain frozen submission metadata as fallback."""
    meta = row.get("submission_meta")
    if not isinstance(meta, dict) or not isinstance(meta.get("responses"), list):
        return row
    attempt = row.get("test_attempts") if isinstance(row.get("test_attempts"), dict) else {}
    manifest = attempt.get("speaking_manifest")
    prompt_by_question = {
        str(item.get("id")): str(item.get("prompt") or "")
        for item in manifest
        if isinstance(item, dict)
    } if isinstance(manifest, list) else {}
    try:
        result = (
            sb.table("speaking_responses")
            .select(
                "id, question_id, part, sequence_number, duration_sec, audio_url, "
                "status, confirmed_at, transcription_status, transcript, fluency_metrics, ai_result"
            )
            .eq("attempt_id", str(row["attempt_id"]))
            .order("sequence_number")
            .execute()
        )
    except Exception:
        return row
    responses = result.data or []
    if not responses:
        return row
    ai_scores = row.get("ai_scores") if isinstance(row.get("ai_scores"), dict) else {}
    evaluation = (
        ai_scores.get("evaluation")
        if isinstance(ai_scores.get("evaluation"), dict)
        else {}
    )
    evidence = _admin_evidence(evaluation)
    enriched = dict(row)
    enriched["submission_meta"] = {
        **meta,
        "responses": [
            {
                "response_id": item["id"],
                "question_id": item["question_id"],
                "part": item["part"],
                "sequence_number": item["sequence_number"],
                "duration_sec": item["duration_sec"],
                "audio_url": item["audio_url"],
                "prompt": prompt_by_question.get(str(item["question_id"])),
                "status": item.get("status"),
                "confirmed_at": item.get("confirmed_at"),
                "transcription_status": item.get("transcription_status"),
                "transcript": item.get("transcript"),
                "fluency_metrics": item.get("fluency_metrics"),
                "ai_status": ai_scores.get("status"),
                "ai_evidence": [
                    ev for ev in evidence
                    if isinstance(ev, dict)
                    and str(ev.get("response_id")) == str(item["id"])
                ],
                "ai_result": item.get("ai_result"),
            }
            for item in responses
        ],
    }
    return enriched


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
    raw_scores = row.get("ai_scores")
    ai_scores = raw_scores if isinstance(raw_scores, dict) else {}
    attempt_metrics = (
        ai_scores.get("fluency_metrics")
        if isinstance(ai_scores.get("fluency_metrics"), dict)
        else None
    )
    raw_part_metrics = ai_scores.get("part_metrics")
    if isinstance(raw_part_metrics, dict):
        part_metrics = raw_part_metrics
    elif attempt_metrics is not None:
        meta = row.get("submission_meta")
        legacy_part = int(meta.get("part") or 1) if isinstance(meta, dict) else 1
        part_metrics = {str(legacy_part): attempt_metrics}
    else:
        part_metrics = {}

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
        part_metrics=part_metrics,
        attempt_metrics=attempt_metrics,
        response_metrics=(
            ai_scores.get("response_metrics")
            if isinstance(ai_scores.get("response_metrics"), list)
            else []
        ),
        transcription_progress=(
            ai_scores.get("transcription_progress")
            if isinstance(ai_scores.get("transcription_progress"), dict)
            else None
        ),
        ai_status=str(ai_scores.get("status")) if ai_scores.get("status") else None,
        ai_evidence=_admin_evidence(ai_scores.get("evaluation")),
        ai_pronunciation_advisory=_admin_pronunciation_advisory(
            ai_scores.get("evaluation")
        ),
        evaluation_status=row.get("evaluation_status"),
        evaluation_error=row.get("evaluation_error"),
        approval_version=int(row.get("approval_version") or 0),
        reopened_at=(
            _parse_dt(row["reopened_at"]) if row.get("reopened_at") else None
        ),
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
            "*, test_attempts(user_id, speaking_manifest, users(full_name, email, target_band))"
        )
        .eq("id", str(review_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    return _detail_from_row(sb, _hydrate_response_meta(sb, result.data[0]))


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
    request_hash = _approval_request_hash(body)
    existing = (
        sb.table("speaking_reviews")
        .select(
            "id, status, ai_scores, attempt_id, audio_url, "
            "approval_idempotency_key, approval_request_hash"
        )
        .eq("id", str(review_id))
        .limit(1)
        .execute()
    ).data
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    if str(existing[0].get("status")) == "completed":
        if existing[0].get("approval_idempotency_key") == body.idempotency_key:
            stored_hash = existing[0].get("approval_request_hash")
            if stored_hash and stored_hash != request_hash:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail="Approval idempotency key was already used with a different payload.",
                )
            attempt_id = existing[0].get("attempt_id")
            if attempt_id:
                _invalidate_speaking_result_caches(sb, attempt_id)
            return get_speaking_detail(review_id)
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Review is already completed.")
    if not body.audio_confirmed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Examiner must confirm that all audio was reviewed.",
        )

    attempt_id = existing[0].get("attempt_id")
    response_rows = (
        sb.table("speaking_responses")
        .select("id, question_id, status")
        .eq("attempt_id", str(attempt_id))
        .execute()
    ).data or []
    if response_rows and any(str(row.get("status")) != "confirmed" for row in response_rows):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="All Speaking response audio must be confirmed before approval.",
        )
    attempt_rows = (
        sb.table("test_attempts")
        .select("speaking_manifest")
        .eq("id", str(attempt_id))
        .limit(1)
        .execute()
    ).data or []
    manifest = (
        attempt_rows[0].get("speaking_manifest")
        if attempt_rows and isinstance(attempt_rows[0].get("speaking_manifest"), list)
        else []
    )
    if manifest:
        expected_question_ids = {
            str(item.get("id"))
            for item in manifest
            if isinstance(item, dict) and item.get("id")
        }
        confirmed_question_ids = {
            str(row.get("question_id"))
            for row in response_rows
            if str(row.get("status")) == "confirmed" and row.get("question_id")
        }
        if not expected_question_ids or confirmed_question_ids != expected_question_ids:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Every expected Speaking response must be confirmed before approval.",
            )
    if not response_rows and not existing[0].get("audio_url"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Review has no confirmed audio.")

    scores = body.human_criteria_scores.model_dump()
    human_band = compute_overall_band(scores)
    raw_ai = existing[0].get("ai_scores")
    ai_scores = raw_ai if isinstance(raw_ai, dict) else None
    ai_criteria = ai_scores_to_criteria(ai_scores)
    ai_band = compute_overall_band(ai_criteria) if ai_criteria else None
    from app.admin.review_comparison import approve_audit_metadata, is_overridden

    overridden = is_overridden(
        human_criteria=scores,
        ai_criteria=ai_criteria,
        human_overall=human_band,
        ai_overall=ai_band,
    )
    if overridden and not str(body.ai_override_note or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An AI override note is required for a material score difference.",
        )
    audit_metadata = approve_audit_metadata(
        human_band=human_band,
        human_criteria=scores,
        ai_band=ai_band,
        ai_criteria=ai_criteria,
    )
    try:
        approval = sb.rpc(
            "approve_speaking_review_atomic",
            {
                "p_review_id": str(review_id),
                "p_admin_id": str(admin_id),
                "p_idempotency_key": body.idempotency_key,
                "p_request_hash": request_hash,
                "p_scores": scores,
                "p_human_band": human_band,
                "p_notes": body.reviewer_notes,
                "p_override_note": body.ai_override_note,
                "p_audit_metadata": audit_metadata,
            },
        ).execute()
    except Exception as exc:
        message = str(exc)
        if "idempotency_payload_mismatch" in message:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Approval idempotency key was already used with a different payload.",
            ) from exc
        if "review_completed" in message:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Review is already completed.") from exc
        raise
    approval_data = approval.data
    if isinstance(approval_data, list):
        approval_data = approval_data[0] if approval_data else {}
    applied = bool((approval_data or {}).get("applied"))
    if applied and attempt_id:
        _invalidate_speaking_result_caches(sb, attempt_id)

    return get_speaking_detail(review_id)


def reopen_speaking_review(
    *,
    review_id: UUID,
    body: ReopenSpeakingReviewRequest,
    admin_id: UUID,
) -> SpeakingReviewDetail:
    sb = get_supabase()
    existing = (
        sb.table("speaking_reviews")
        .select("attempt_id")
        .eq("id", str(review_id))
        .limit(1)
        .execute()
    ).data
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Review not found.")
    attempt_id = existing[0].get("attempt_id")
    try:
        result = sb.rpc(
            "reopen_speaking_review_atomic",
            {
                "p_review_id": str(review_id),
                "p_admin_id": str(admin_id),
                "p_reason": body.reason,
            },
        ).execute()
    except Exception as exc:
        message = str(exc)
        if "review_not_found" in message:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Review not found.") from exc
        if "review_not_completed" in message:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Only completed reviews can be reopened."
            ) from exc
        raise
    if not result.data:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Review could not be reopened.")
    if attempt_id:
        _invalidate_speaking_result_caches(sb, attempt_id)
    return get_speaking_detail(review_id)
