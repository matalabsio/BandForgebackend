"""Writing Skill track selection (user_program_usage.exam_module)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, status

from app.practice.writing_skill_course import get_writing_skill_course_context
from app.security.entitlements import resolve_entitlements

ExamModuleValue = Literal["academic", "general_training"]
VALID_EXAM_MODULES = frozenset({"academic", "general_training"})

TRACK_LOCKED_DETAIL = (
    "exam_module cannot be changed after Writing Skill progress has started"
)
TRACK_CONFLICT_DETAIL = "exam_module is already set to a different track"
NO_USAGE_DETAIL = "Writing Skill program usage not found."


def _require_writing_skill_plan(user_id: UUID) -> None:
    ent = resolve_entitlements(user_id)
    if not ent["writing_skill"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Writing Skill entitlement required.",
        )


def writing_skill_progress_started(*, user_id: UUID, plan_id: str) -> bool:
    """True when any progress exists for hubs attached to this Writing Skill plan."""
    from app.db.supabase_client import get_supabase
    from app.practice import repository

    sb = get_supabase()
    result = (
        sb.table("program_content_items")
        .select("item_id")
        .eq("plan_id", str(plan_id))
        .eq("item_type", "practice_hub")
        .execute()
    )
    hub_ids = {
        str(row.get("item_id") or "")
        for row in (result.data or [])
        if row.get("item_id")
    }
    if not hub_ids:
        return False
    progress = repository.get_user_progress_map(user_id)
    for hub_id, row in progress.items():
        if hub_id not in hub_ids:
            continue
        # Any progress row for a program hub counts as started.
        if row:
            return True
    return False


def set_writing_skill_exam_module(
    *, user_id: UUID, exam_module: str
) -> dict[str, Any]:
    """Set/lock Writing Skill course track on user_program_usage.

    Idempotent when already equal. Allows change only before progress starts.
    Synchronizes users.exam_module as a non-authoritative preference.
    """
    exam_module = str(exam_module or "").strip().lower()
    if exam_module not in VALID_EXAM_MODULES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="exam_module must be academic or general_training",
        )

    _require_writing_skill_plan(user_id)
    ctx = get_writing_skill_course_context(user_id)
    usage = ctx.get("usage")
    if not usage or not usage.get("id"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=NO_USAGE_DETAIL)

    usage_id = str(usage["id"])
    current = usage.get("exam_module")
    if current == exam_module:
        _sync_profile_exam_module(user_id=user_id, exam_module=exam_module)
        return {
            "exam_module": exam_module,
            "usage_id": usage_id,
            "changed": False,
        }

    allow_change = False
    if current in VALID_EXAM_MODULES and current != exam_module:
        if writing_skill_progress_started(
            user_id=user_id, plan_id=str(ctx["plan_id"])
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=TRACK_LOCKED_DETAIL,
            )
        allow_change = True

    from app.payments import repository as payments_repo

    updated = payments_repo.set_user_program_exam_module_atomic(
        usage_id=usage_id,
        exam_module=exam_module,
        allow_change=allow_change or current is None,
    )
    if not updated:
        # Concurrent writer won, or locked after re-check.
        refreshed = payments_repo.get_user_program_usage_by_id(usage_id)
        if refreshed and refreshed.get("exam_module") == exam_module:
            _sync_profile_exam_module(user_id=user_id, exam_module=exam_module)
            return {
                "exam_module": exam_module,
                "usage_id": usage_id,
                "changed": False,
            }
        if refreshed and refreshed.get("exam_module") in VALID_EXAM_MODULES:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=TRACK_CONFLICT_DETAIL
                if not writing_skill_progress_started(
                    user_id=user_id, plan_id=str(ctx["plan_id"])
                )
                else TRACK_LOCKED_DETAIL,
            )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=TRACK_CONFLICT_DETAIL,
        )

    final_module = str(updated.get("exam_module") or exam_module)
    _sync_profile_exam_module(user_id=user_id, exam_module=final_module)
    return {
        "exam_module": final_module,
        "usage_id": usage_id,
        "changed": current != final_module,
    }


def _sync_profile_exam_module(*, user_id: UUID, exam_module: str) -> None:
    """Best-effort preference sync; never authoritative for course access."""
    try:
        from app.db.supabase_client import get_supabase

        get_supabase().table("users").update({"exam_module": exam_module}).eq(
            "id", str(user_id)
        ).execute()
    except Exception:
        pass
