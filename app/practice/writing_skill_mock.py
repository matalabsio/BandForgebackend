"""Writing Skill mock unlock, allotment, and atomic quota consumption."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.practice.writing_skill_course import (
    EXAM_MODULE_REQUIRED_DETAIL,
    get_writing_skill_course_context,
    list_writing_skill_hub_rows,
    require_writing_skill_exam_module,
)
from app.security.entitlements import resolve_entitlements

MOCK_QUOTA_EXHAUSTED_DETAIL = "Writing Skill mock quota has already been used."
MOCK_NOT_CONFIGURED_DETAIL = (
    "No Writing Skill mock is configured for your exam track."
)
MOCK_NOT_ALLOTTED_DETAIL = "This mock is not part of your Writing Skill program."
COURSE_INCOMPLETE_DETAIL = (
    "Complete all Writing Skill practice sets to unlock your mock."
)


def writing_skill_course_completion(
    *, user_id: UUID
) -> tuple[int, int, list[dict[str, Any]]]:
    """Return (completed, total, hub_rows) from the Writing Skill program pool."""
    rows = list_writing_skill_hub_rows(user_id=user_id)
    from app.practice import repository

    progress = repository.get_user_progress_map(user_id)
    completed = 0
    for row in rows:
        hid = str(repository._flatten_hub_row(row)["id"])
        if progress.get(hid, {}).get("status") == "completed":
            completed += 1
    return completed, len(rows), rows


def list_writing_skill_mock_items(
    *, plan_id: str, exam_module: str
) -> list[dict[str, Any]]:
    from app.db.supabase_client import get_supabase

    sb = get_supabase()
    result = (
        sb.table("program_content_items")
        .select("id, item_id, exam_module, sort_order, is_active, item_type")
        .eq("plan_id", str(plan_id))
        .eq("item_type", "mock_test")
        .eq("is_active", True)
        .in_("exam_module", [exam_module, "both"])
        .order("sort_order")
        .execute()
    )
    return list(result.data or [])


def resolve_writing_skill_mock_test_id(*, user_id: UUID) -> str:
    """Resolve the allotted mock_test id for the user's Writing Skill track."""
    ctx = get_writing_skill_course_context(user_id)
    exam_module = require_writing_skill_exam_module(ctx)
    items = list_writing_skill_mock_items(
        plan_id=str(ctx["plan_id"]), exam_module=exam_module
    )
    for item in items:
        mock_id = str(item.get("item_id") or "").strip()
        if not mock_id:
            continue
        # Polymorphic: verify mock_tests row exists.
        from app.db.supabase_client import get_supabase

        row = (
            get_supabase()
            .table("mock_tests")
            .select("id")
            .eq("id", mock_id)
            .limit(1)
            .execute()
        )
        if row.data:
            return mock_id
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=MOCK_NOT_CONFIGURED_DETAIL,
    )


def is_writing_skill_allotted_mock(*, user_id: UUID, mock_test_id: UUID | str) -> bool:
    try:
        allotted = resolve_writing_skill_mock_test_id(user_id=user_id)
    except HTTPException:
        return False
    return str(allotted) == str(mock_test_id)


def user_has_attempt_for_mock(*, user_id: UUID, mock_test_id: UUID | str) -> bool:
    """True when the user already started this mock (any module / mock_attempt)."""
    from app.db.supabase_client import get_supabase

    sb = get_supabase()
    ma = (
        sb.table("mock_attempts")
        .select("id")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(mock_test_id))
        .limit(1)
        .execute()
    )
    if ma.data:
        return True
    ta = (
        sb.table("test_attempts")
        .select("id")
        .eq("user_id", str(user_id))
        .eq("mock_test_id", str(mock_test_id))
        .limit(1)
        .execute()
    )
    return bool(ta.data)


def assert_writing_skill_mock_access(*, user_id: UUID) -> dict[str, Any]:
    """Deny unless entitlement, usage, track, course complete, and quota remain.

    Used for unlock / first-start authorization. Prefer
    ``assert_writing_skill_mock_for_test`` at start endpoints (handles resume).
    """
    ent = resolve_entitlements(user_id)
    if not ent["writing_skill"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Writing Skill entitlement required.",
        )
    if ent["full_skill_program"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Writing Skill mock quota does not apply to Full Skill Program.",
        )

    ctx = get_writing_skill_course_context(user_id)
    usage = ctx.get("usage")
    if not usage:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Writing Skill program usage not found.",
        )
    require_writing_skill_exam_module(ctx)

    completed, total, _rows = writing_skill_course_completion(user_id=user_id)
    if total <= 0 or completed < total:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "message": COURSE_INCOMPLETE_DETAIL,
                "completed": completed,
                "required": total,
            },
        )

    granted = int(usage.get("mocks_granted") or 0)
    used = int(usage.get("mocks_used") or 0)
    if granted <= 0 or used >= granted:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=MOCK_QUOTA_EXHAUSTED_DETAIL,
        )

    mock_test_id = resolve_writing_skill_mock_test_id(user_id=user_id)
    return {
        "usage": usage,
        "usage_id": str(usage["id"]),
        "mock_test_id": mock_test_id,
        "completed": completed,
        "required": total,
        "mocks_granted": granted,
        "mocks_used": used,
    }


def assert_writing_skill_mock_for_test(
    *, user_id: UUID, mock_test_id: UUID | str
) -> dict[str, Any]:
    """Authorize start/resume of the allotted Writing Skill mock."""
    ent = resolve_entitlements(user_id)
    if not ent["writing_skill"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Writing Skill entitlement required.",
        )
    if ent["full_skill_program"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Writing Skill mock quota does not apply to Full Skill Program.",
        )

    ctx = get_writing_skill_course_context(user_id)
    usage = ctx.get("usage")
    if not usage:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Writing Skill program usage not found.",
        )
    require_writing_skill_exam_module(ctx)

    completed, total, _rows = writing_skill_course_completion(user_id=user_id)
    if total <= 0 or completed < total:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "message": COURSE_INCOMPLETE_DETAIL,
                "completed": completed,
                "required": total,
            },
        )

    allotted = resolve_writing_skill_mock_test_id(user_id=user_id)
    if str(allotted) != str(mock_test_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=MOCK_NOT_ALLOTTED_DETAIL,
        )

    granted = int(usage.get("mocks_granted") or 0)
    used = int(usage.get("mocks_used") or 0)
    prior = user_has_attempt_for_mock(user_id=user_id, mock_test_id=mock_test_id)
    if granted <= 0:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=MOCK_QUOTA_EXHAUSTED_DETAIL,
        )
    if used >= granted and not prior:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=MOCK_QUOTA_EXHAUSTED_DETAIL,
        )

    return {
        "usage": usage,
        "usage_id": str(usage["id"]),
        "mock_test_id": allotted,
        "completed": completed,
        "required": total,
        "mocks_granted": granted,
        "mocks_used": used,
        "should_consume": used < granted and not prior,
    }


def consume_writing_skill_mock_quota(*, usage_id: str) -> dict[str, Any]:
    """Atomic consume; raises 403 if quota exhausted (concurrent loser)."""
    from app.payments import repository as payments_repo

    row = payments_repo.consume_user_program_mock_quota_atomic(usage_id=usage_id)
    if not row:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=MOCK_QUOTA_EXHAUSTED_DETAIL,
        )
    return row


def writing_skill_mock_unlock_status(*, user_id: UUID) -> dict[str, Any]:
    """Status payload for practice mock-unlock (no consumption)."""
    ent = resolve_entitlements(user_id)
    if not ent["writing_skill"] or ent["full_skill_program"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Writing Skill mock status requires Writing Skill entitlement.",
        )
    ctx = get_writing_skill_course_context(user_id)
    if ctx.get("exam_module") not in ("academic", "general_training"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=EXAM_MODULE_REQUIRED_DETAIL,
        )
    completed, total, _ = writing_skill_course_completion(user_id=user_id)
    usage = ctx.get("usage") or {}
    granted = int(usage.get("mocks_granted") or 0)
    used = int(usage.get("mocks_used") or 0)
    quota_ok = granted > 0 and used < granted
    course_ok = total > 0 and completed >= total
    mock_test_id: str | None = None
    if course_ok and quota_ok:
        try:
            mock_test_id = resolve_writing_skill_mock_test_id(user_id=user_id)
        except HTTPException:
            mock_test_id = None
    # Never leak allotted mock id while still locked (course/quota incomplete).
    unlocked = bool(course_ok and quota_ok and mock_test_id)
    return {
        "skill": "writing",
        "unlocked": unlocked,
        "completed": completed,
        "required": total,
        "mock_test_id": mock_test_id if unlocked else None,
        "mocks_granted": granted,
        "mocks_used": used,
        "exam_module": ctx.get("exam_module"),
    }


def maybe_consume_after_new_mock_start(
    *, user_id: UUID, mock_test_id: UUID | str, created_new: bool
) -> None:
    """Consume Writing Skill quota only when a new attempt was created."""
    if not created_new:
        return
    ent = resolve_entitlements(user_id)
    if ent["full_skill_program"] or not ent["writing_skill"]:
        return
    # Only consume for the allotted program mock.
    access = assert_writing_skill_mock_for_test(
        user_id=user_id, mock_test_id=mock_test_id
    )
    consume_writing_skill_mock_quota(usage_id=str(access["usage_id"]))
