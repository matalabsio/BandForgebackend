"""Phase 1 personalized practice assignment engine.

Soft-repeat + difficulty-ordered pools + per-skill cursors derived from
user_hub_progress. Pure helpers stay free of FastAPI / HTTP concerns.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from app.practice import repository

SKILLS = repository.SKILLS


def assign_hub_for_day(
    *,
    hub_ids: list[str],
    cursor: int,
    day_offset: int,
    previous_hub_id: str | None = None,
) -> str | None:
    """Pick a hub with soft-repeat wrap and anti-consecutive rule.

    index = (cursor + day_offset) % pool_size
    If that hub equals previous_hub_id and pool_size > 1, advance by 1.
    """
    if not hub_ids:
        return None
    n = len(hub_ids)
    idx = (max(int(cursor), 0) + max(int(day_offset), 0)) % n
    hub = hub_ids[idx]
    if previous_hub_id and n > 1 and str(hub) == str(previous_hub_id):
        idx = (idx + 1) % n
        hub = hub_ids[idx]
    return str(hub)


def _ordered_ids() -> dict[str, list[str]]:
    from app.practice import catalog

    return catalog.get_ordered_hub_ids_by_skill()


def skill_cursor(
    *,
    user_id: UUID | None = None,
    skill: str,
    progress_map: dict[str, dict[str, Any]] | None = None,
    hub_ids: list[str] | None = None,
) -> int:
    """Independent per-skill cursor = completed count ∩ assignable ordered pool."""
    skill = str(skill or "").strip().lower()
    if skill not in SKILLS:
        return 0
    ids = hub_ids if hub_ids is not None else (_ordered_ids().get(skill) or [])
    if not ids:
        return 0
    if progress_map is None:
        if user_id is None:
            return 0
        progress_map = repository.get_user_progress_map(user_id)
    completed = 0
    for hid in ids:
        if str(progress_map.get(str(hid), {}).get("status") or "") == "completed":
            completed += 1
    return completed


def cursors_by_skill(
    *,
    user_id: UUID,
    progress_map: dict[str, dict[str, Any]] | None = None,
    ordered_ids: dict[str, list[str]] | None = None,
) -> dict[str, int]:
    progress = (
        progress_map
        if progress_map is not None
        else repository.get_user_progress_map(user_id)
    )
    pools = ordered_ids if ordered_ids is not None else _ordered_ids()
    return {
        skill: skill_cursor(
            user_id=user_id,
            skill=skill,
            progress_map=progress,
            hub_ids=pools.get(skill) or [],
        )
        for skill in SKILLS
    }


def pick_hub_for_slot(
    *,
    skill: str,
    day_index: int,
    slot_index: int = 0,
    completed_count: int | None = None,
    previous_hub_id: str | None = None,
    hub_ids: list[str] | None = None,
    weak_tags: list[str] | None = None,
    hub_tags_by_id: dict[str, list[str]] | None = None,
) -> str | None:
    """Thin wrapper: load difficulty-ordered pool, soft-repeat assign.

    When ``weak_tags`` is set, re-order the pool so overlapping hubs come first.
    ``completed_count`` is the skill cursor. ``slot_index`` unused for offset.
    """
    del slot_index  # reserved; skills share day stacks
    from app.practice.weakness import order_pool_for_weakness

    ids = hub_ids if hub_ids is not None else (_ordered_ids().get(skill) or [])
    if weak_tags:
        tags_map = hub_tags_by_id
        if tags_map is None:
            from app.practice.catalog import get_hub_skill_tags_by_id

            tags_map = get_hub_skill_tags_by_id()
        ids = order_pool_for_weakness(
            ids, weak_tags=weak_tags, hub_tags_by_id=tags_map
        )
    cursor = int(completed_count) if completed_count is not None else 0
    return assign_hub_for_day(
        hub_ids=ids,
        cursor=cursor,
        day_offset=max(int(day_index), 0),
        previous_hub_id=previous_hub_id,
    )


def rewrite_plan_hubs(
    study_plan: dict[str, Any],
    *,
    cursors: dict[str, int],
    prep_start: date | None = None,
    ordered_ids: dict[str, list[str]] | None = None,
    href_builder: Any | None = None,
    weak_tags_by_skill: dict[str, list[str]] | None = None,
    hub_tags_by_id: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Rewrite every task hub_id/href with the soft-repeat engine (serve-time truth).

    Walks days chronologically; tracks previous hub per skill for anti-consecutive.
    When weak_tags_by_skill is set, pools are re-ordered for tag overlap first.
    ``href_builder(skill=, hub_id=, task_type=, task_id=) -> str`` optional.
    """
    if not isinstance(study_plan, dict):
        return study_plan

    from app.practice.weakness import order_pool_for_weakness

    pools = ordered_ids if ordered_ids is not None else _ordered_ids()
    tags_map = hub_tags_by_id
    if weak_tags_by_skill and tags_map is None:
        from app.practice.catalog import get_hub_skill_tags_by_id

        tags_map = get_hub_skill_tags_by_id()

    # Precompute weakness-ordered pools once
    ordered_pools: dict[str, list[str]] = {}
    for skill in SKILLS:
        base = list(pools.get(skill) or [])
        weak = (weak_tags_by_skill or {}).get(skill) or []
        if weak and tags_map:
            ordered_pools[skill] = order_pool_for_weakness(
                base, weak_tags=weak, hub_tags_by_id=tags_map
            )
        else:
            ordered_pools[skill] = base

    start = prep_start
    if start is None:
        raw = study_plan.get("prep_start")
        if raw:
            try:
                start = date.fromisoformat(str(raw)[:10])
            except ValueError:
                start = None

    previous: dict[str, str | None] = {s: None for s in SKILLS}
    weeks_out: list[dict[str, Any]] = []

    # Flatten days in date order while preserving week structure
    day_entries: list[tuple[int, int, dict[str, Any]]] = []
    for wi, week in enumerate(study_plan.get("weeks") or []):
        if not isinstance(week, dict):
            continue
        for di, day in enumerate(week.get("days") or []):
            if isinstance(day, dict):
                day_entries.append((wi, di, day))

    def day_sort_key(item: tuple[int, int, dict[str, Any]]) -> tuple[str, int, int]:
        _wi, _di, day = item
        return (str(day.get("date") or ""), _wi, _di)

    day_entries.sort(key=day_sort_key)

    # Map (wi, di) -> rewritten day
    rewritten_days: dict[tuple[int, int], dict[str, Any]] = {}

    for wi, di, day in day_entries:
        day_date_s = str(day.get("date") or "")
        day_offset = 0
        if start is not None and day_date_s:
            try:
                day_offset = max((date.fromisoformat(day_date_s[:10]) - start).days, 0)
            except ValueError:
                day_offset = 0

        tasks_out: list[dict[str, Any]] = []
        # Assign once per skill per day (watch/practice/submit share hub)
        hub_for_skill: dict[str, str | None] = {}
        for task in day.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            skill = str(task.get("module") or "").strip().lower()
            task_out = dict(task)
            if skill in SKILLS:
                if skill not in hub_for_skill:
                    hub = assign_hub_for_day(
                        hub_ids=ordered_pools.get(skill) or [],
                        cursor=int(cursors.get(skill) or 0),
                        day_offset=day_offset,
                        previous_hub_id=previous.get(skill),
                    )
                    hub_for_skill[skill] = hub
                    if hub:
                        previous[skill] = hub
                hub_id = hub_for_skill.get(skill)
                task_out["hub_id"] = hub_id
                if href_builder is not None:
                    task_type = task_out.get("task_type") or "practice"
                    task_id = task_out.get("id")
                    task_out["href"] = href_builder(
                        skill=skill,
                        hub_id=hub_id,
                        task_type=task_type,
                        task_id=task_id,
                    )
            tasks_out.append(task_out)

        rewritten_days[(wi, di)] = {**day, "tasks": tasks_out}

    for wi, week in enumerate(study_plan.get("weeks") or []):
        if not isinstance(week, dict):
            weeks_out.append(week)
            continue
        days_list = []
        for di, day in enumerate(week.get("days") or []):
            days_list.append(rewritten_days.get((wi, di), day))
        weeks_out.append({**week, "days": days_list})

    assigned: list[str] = []
    for day in rewritten_days.values():
        for t in day.get("tasks") or []:
            hid = t.get("hub_id")
            if hid and hid not in assigned:
                assigned.append(str(hid))

    return {**study_plan, "weeks": weeks_out, "assigned_hub_ids": assigned}
