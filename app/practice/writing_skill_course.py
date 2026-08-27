"""Writing Skill pack course pool and hard sequential unlock."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.payments.constants import (
    DUAL_BUNDLE_SLUG,
    PROGRAM_SKILL_WRITING,
    WRITING_SKILL_SLUG,
)
from app.practice import repository

EXAM_MODULE_REQUIRED_DETAIL = (
    "exam_module must be selected before starting Writing Skill"
)
NOT_IN_PROGRAM_DETAIL = "This practice set is not part of your Writing Skill program."
LOCKED_HUB_MESSAGE = "Complete the previous practice set to unlock this one."


def get_writing_skill_course_context(user_id: UUID) -> dict[str, Any]:
    """Active writing_skill or dual_bundle subscription + writing usage row.

    Dual reuses the existing writing_skill plan_id for PCI (no dual catalog).
    """
    from app.payments import repository as payments_repo

    dual_sub_id: str | None = None

    for sub in payments_repo.list_active_subscriptions(user_id):
        plans = sub.get("plans") or {}
        if not isinstance(plans, dict):
            continue
        slug = plans.get("slug")
        sub_id = sub.get("id")
        if not sub_id:
            continue

        if slug == WRITING_SKILL_SLUG:
            plan_id = sub.get("plan_id")
            if not plan_id:
                continue
            usage = payments_repo.get_user_program_usage_by_subscription(
                sub_id, skill=PROGRAM_SKILL_WRITING
            )
            return {
                "subscription_id": str(sub_id),
                "plan_id": str(plan_id),
                "usage": usage,
                "exam_module": (usage or {}).get("exam_module"),
            }

        if slug == DUAL_BUNDLE_SLUG and dual_sub_id is None:
            dual_sub_id = str(sub_id)

    if dual_sub_id is not None:
        writing_plan = payments_repo.get_plan_row_by_slug(WRITING_SKILL_SLUG)
        if writing_plan and writing_plan.get("id"):
            usage = payments_repo.get_user_program_usage_by_subscription(
                dual_sub_id, skill=PROGRAM_SKILL_WRITING
            )
            return {
                "subscription_id": dual_sub_id,
                "plan_id": str(writing_plan["id"]),
                "usage": usage,
                "exam_module": (usage or {}).get("exam_module"),
            }

    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail="Writing Skill entitlement required.",
    )


def require_writing_skill_exam_module(ctx: dict[str, Any]) -> str:
    module = ctx.get("exam_module")
    if module in ("academic", "general_training"):
        return str(module)
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        detail=EXAM_MODULE_REQUIRED_DETAIL,
    )


def list_writing_skill_program_items(
    *, plan_id: str, exam_module: str
) -> list[dict[str, Any]]:
    """Active practice_hub attachments for plan + track (includes exam_module=both)."""
    from app.db.supabase_client import get_supabase

    sb = get_supabase()
    result = (
        sb.table("program_content_items")
        .select("id, item_id, exam_module, sort_order, is_active, item_type")
        .eq("plan_id", str(plan_id))
        .eq("item_type", "practice_hub")
        .eq("is_active", True)
        .in_("exam_module", [exam_module, "both"])
        .order("sort_order")
        .execute()
    )
    return list(result.data or [])


def list_writing_skill_hub_rows(*, user_id: UUID) -> list[dict[str, Any]]:
    """Ordered, validated Writing Skill hubs for the user's purchase track.

    Raises 409 when exam_module is unset. Returns [] when inventory is empty.
    """
    ctx = get_writing_skill_course_context(user_id)
    exam_module = require_writing_skill_exam_module(ctx)
    items = list_writing_skill_program_items(
        plan_id=str(ctx["plan_id"]), exam_module=exam_module
    )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        hub_id = str(item.get("item_id") or "")
        if not hub_id or hub_id in seen:
            continue
        row = repository.get_hub_by_id(hub_id)
        if not row or not repository.is_hub_assignable(row):
            continue
        flat_skill = repository._flatten_hub_row(row).get("skill")
        if flat_skill != "writing":
            continue
        # Stamp program sort_order onto the hub row for list/sequence.
        stamped = dict(row)
        stamped["_program_sort_order"] = int(item.get("sort_order") or 0)
        stamped["_program_exam_module"] = str(item.get("exam_module") or exam_module)
        out.append(stamped)
        seen.add(hub_id)
    out.sort(key=lambda r: int(r.get("_program_sort_order") or 0))
    return out


def writing_skill_ordered_hub_ids(hub_rows: list[dict[str, Any]]) -> list[str]:
    return [str(repository._flatten_hub_row(r)["id"]) for r in hub_rows]


def accessible_writing_skill_hub_ids(
    *,
    ordered_hub_ids: list[str],
    progress_map: dict[str, dict[str, Any]],
) -> set[str]:
    """Hard sequential: completed stay open; only next incomplete is unlocked."""
    accessible: set[str] = set()
    unlocked_next = True
    for hub_id in ordered_hub_ids:
        status = str(progress_map.get(hub_id, {}).get("status") or "pending")
        if status == "completed":
            accessible.add(hub_id)
            continue
        if unlocked_next:
            accessible.add(hub_id)
            unlocked_next = False
    return accessible


def assert_writing_skill_hub_accessible(
    *, user_id: UUID, hub_id: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Server-side hard sequence for Writing Skill (deep-link safe)."""
    hub_id = str(hub_id)
    row = repository.get_hub_by_id(hub_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Hub not found")

    flat = repository._flatten_hub_row(row)
    if flat.get("skill") != "writing":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Your plan does not include this practice skill.",
        )

    hub_rows = list_writing_skill_hub_rows(user_id=user_id)
    ordered_ids = writing_skill_ordered_hub_ids(hub_rows)
    if hub_id not in ordered_ids:
        # Exists globally but not in this purchase/track/inventory.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=NOT_IN_PROGRAM_DETAIL,
        )

    progress_map = repository.get_user_progress_map(user_id)
    allowed = accessible_writing_skill_hub_ids(
        ordered_hub_ids=ordered_ids, progress_map=progress_map
    )
    if hub_id not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=LOCKED_HUB_MESSAGE,
        )

    # Prefer stamped row from course list (program sort_order).
    for stamped in hub_rows:
        if str(stamped.get("id")) == hub_id:
            flat_out = repository._flatten_hub_row(stamped)
            flat_out["sort_order"] = int(stamped.get("_program_sort_order") or 0)
            return flat_out, progress_map
    return flat, progress_map
