"""Personalized Question Bank assignment: unique unused-set picker.

Pool is the live assignable Question Bank catalog. Used is the union of
ledger, hub progress, and hubs already on the current plan. Never wraps.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from app.practice import repository

logger = logging.getLogger(__name__)
SKILLS = repository.SKILLS


def pick_unused_hub(
    *,
    hub_ids: list[str],
    used_hub_ids: set[str] | None = None,
    used_set_ids: set[str] | None = None,
    hub_to_set: dict[str, str] | None = None,
) -> str | None:
    """Return the first unused hub. Never wraps or repeats a used set/hub."""
    used_h = used_hub_ids if used_hub_ids is not None else set()
    used_s = used_set_ids if used_set_ids is not None else set()
    mapping = hub_to_set or {}
    for raw in hub_ids:
        hid = str(raw or "").strip()
        if not hid or hid in used_h:
            continue
        sid = str(mapping.get(hid) or "").strip()
        if sid and sid in used_s:
            continue
        return hid
    return None


def _mark_used(
    hub_id: str,
    set_id: str,
    used_hub_ids: set[str] | None,
    used_set_ids: set[str] | None,
) -> None:
    if used_hub_ids is not None:
        used_hub_ids.add(hub_id)
    if set_id and used_set_ids is not None:
        used_set_ids.add(set_id)


def assign_hub_for_day(
    *,
    hub_ids: list[str],
    cursor: int = 0,
    day_offset: int = 0,
    previous_hub_id: str | None = None,
    used_hub_ids: set[str] | None = None,
    used_set_ids: set[str] | None = None,
    hub_to_set: dict[str, str] | None = None,
) -> str | None:
    """Pick the next unused hub for a day. ``cursor`` / wrap args are ignored."""
    del cursor, day_offset, previous_hub_id
    return pick_unused_hub(
        hub_ids=hub_ids,
        used_hub_ids=used_hub_ids,
        used_set_ids=used_set_ids,
        hub_to_set=hub_to_set,
    )


def _ordered_ids() -> dict[str, list[str]]:
    from app.practice import catalog

    return catalog.get_ordered_question_bank_ids_by_skill()


def skill_cursor(
    *,
    user_id: UUID | None = None,
    skill: str,
    progress_map: dict[str, dict[str, Any]] | None = None,
    hub_ids: list[str] | None = None,
) -> int:
    """Completed count ∩ assignable ordered pool (mock-unlock, not picking)."""
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


def collect_used_assignment_ids(
    *,
    user_id: UUID | str | None = None,
    study_plan: dict[str, Any] | None = None,
    progress_map: dict[str, dict[str, Any]] | None = None,
    hub_to_set: dict[str, str] | None = None,
) -> tuple[set[str], set[str]]:
    """used hubs/sets = ledger ∪ progress ∪ current plan hub ids."""
    from app.practice.assignment_ledger import hub_ids_from_study_plan, list_user_assignment_ids

    used_hubs: set[str] = set()
    used_sets: set[str] = set()
    mapping = hub_to_set or {}

    def _add_hub(raw: Any) -> None:
        hid = str(raw or "").strip()
        if not hid:
            return
        used_hubs.add(hid)
        sid = str(mapping.get(hid) or "").strip()
        if sid:
            used_sets.add(sid)

    if user_id is not None:
        try:
            ledger_hubs, ledger_sets = list_user_assignment_ids(user_id)
            used_hubs |= ledger_hubs
            used_sets |= ledger_sets
        except Exception:
            pass
    for hid in hub_ids_from_study_plan(study_plan):
        _add_hub(hid)
    for hid in progress_map or {}:
        _add_hub(hid)
    return used_hubs, used_sets


def _claim_candidate(
    *,
    user_id: UUID | str,
    hub_id: str,
    set_id: str,
    skill: str,
    source: str,
    assigned_on: date | str | None,
) -> str:
    from app.practice.assignment_ledger import try_claim_practice_assignment

    return try_claim_practice_assignment(
        user_id=user_id,
        hub_id=hub_id,
        practice_set_id=set_id,
        skill=skill,
        source=source,
        assigned_on=assigned_on,
    )


def pick_hub_for_slot(
    *,
    skill: str,
    day_index: int = 0,
    slot_index: int = 0,
    completed_count: int | None = None,
    previous_hub_id: str | None = None,
    hub_ids: list[str] | None = None,
    weak_tags: list[str] | None = None,
    hub_tags_by_id: dict[str, list[str]] | None = None,
    used_hub_ids: set[str] | None = None,
    used_set_ids: set[str] | None = None,
    hub_to_set: dict[str, str] | None = None,
    user_id: UUID | str | None = None,
    source: str = "plan_generate",
    assigned_on: date | str | None = None,
    claim: bool = False,
    user_exam_module: str | None = None,
    hub_exam_module_by_id: dict[str, str | None] | None = None,
) -> str | None:
    """Pick the next unused Question Bank hub. Never wraps.

    ``day_index`` / ``completed_count`` / ``previous_hub_id`` are accepted for
    call-site compatibility and ignored. Pass mutating ``used_*`` sets so
    successive calls consume the pool uniquely.

    Writing (FSP): when ``skill == writing``, the candidate pool is filtered by
    ``users.exam_module`` vs ``practice_sets.exam_module``. NULL user track yields
    no new Writing assignment. Listening / Reading / Speaking are unchanged.
    """
    del day_index, slot_index, completed_count, previous_hub_id
    skill = str(skill or "").strip().lower()
    if skill not in SKILLS:
        return None

    from app.practice.weakness import order_pool_for_weakness

    ids = list(hub_ids) if hub_ids is not None else list(_ordered_ids().get(skill) or [])
    mapping = dict(hub_to_set or {})

    if skill == "writing":
        from app.practice.writing_track import filter_writing_hub_ids

        exam_map = hub_exam_module_by_id
        if exam_map is None:
            try:
                from app.practice.catalog import get_hub_exam_modules

                exam_map = get_hub_exam_modules()
            except Exception:
                exam_map = {}
        track = user_exam_module
        if track is None and user_id is not None:
            try:
                from app.payments.repository import get_user_exam_module

                track = get_user_exam_module(user_id)
            except Exception:
                track = None
        ids = filter_writing_hub_ids(
            ids,
            hub_exam_module_by_id=exam_map,
            user_exam_module=track,
        )

    if weak_tags:
        tags_map = hub_tags_by_id
        if tags_map is None:
            from app.practice.catalog import get_hub_skill_tags_by_id

            tags_map = get_hub_skill_tags_by_id()
        ids = order_pool_for_weakness(
            ids, weak_tags=weak_tags, hub_tags_by_id=tags_map
        )

    used_h = used_hub_ids if used_hub_ids is not None else set()
    used_s = used_set_ids if used_set_ids is not None else set()

    while True:
        hub = pick_unused_hub(
            hub_ids=ids,
            used_hub_ids=used_h,
            used_set_ids=used_s,
            hub_to_set=mapping,
        )
        if not hub:
            return None
        set_id = str(mapping.get(hub) or "").strip()
        if claim and user_id and set_id:
            try:
                status = _claim_candidate(
                    user_id=user_id,
                    hub_id=hub,
                    set_id=set_id,
                    skill=skill,
                    source=source,
                    assigned_on=assigned_on,
                )
            except Exception:
                logger.exception(
                    "ledger claim failed skill=%s hub=%s; skipping candidate",
                    skill,
                    hub,
                )
                _mark_used(hub, set_id, used_h, used_s)
                continue
            if status == "conflict":
                _mark_used(hub, set_id, used_h, used_s)
                continue
            # claimed or already: this user owns this hub. Reuse it; do not
            # consume a different catalog set.
        _mark_used(hub, set_id, used_h, used_s)
        return hub


def _parse_plan_day(raw: Any) -> date | None:
    text = str(raw or "")[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _existing_hub_for_skill(tasks: list[Any], skill: str) -> str | None:
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("module") or "").strip().lower() != skill:
            continue
        hid = str(task.get("hub_id") or "").strip()
        if hid:
            return hid
    return None


def _should_preserve_assignment(
    *,
    kind: str,
    existing_hub: str | None,
) -> bool:
    """Sticky: past never changes; any existing assignment is kept."""
    if kind == "past":
        return True
    return bool(existing_hub)


def _ledger_orphans_by_skill(
    *,
    user_id: UUID | str | None,
    study_plan: dict[str, Any],
    assignable_by_skill: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Ledger hubs this user owns that are not yet on the calendar.

    Crash recovery: a claim can succeed before plan persist. The next fill
    must place that hub on an empty eligible day instead of consuming a new set.
    Unpublished/unassignable hubs stay on the ledger and are not newly placed.
    """
    if user_id is None:
        return {}
    from app.practice.assignment_ledger import (
        hub_ids_from_study_plan,
        list_user_assignment_ids,
    )

    on_plan = set(hub_ids_from_study_plan(study_plan))
    assignable = {hid for ids in assignable_by_skill.values() for hid in ids}
    out: dict[str, list[str]] = {skill: [] for skill in SKILLS}
    try:
        ledger_hubs, _ledger_sets = list_user_assignment_ids(user_id)
    except Exception:
        logger.exception("failed to load ledger orphans for recovery")
        return {}
    seen: set[str] = set()
    for hid in ledger_hubs:
        if not hid or hid in seen or hid in on_plan or hid not in assignable:
            continue
        seen.add(hid)
        for skill, ids in assignable_by_skill.items():
            if hid in ids:
                out[skill].append(hid)
                break
    return out


def _pop_orphan_hub(orphans: dict[str, list[str]], skill: str) -> str | None:
    pending = orphans.get(skill) or []
    while pending:
        hub = pending.pop(0)
        if hub:
            return hub
    return None


def rewrite_plan_hubs(
    study_plan: dict[str, Any],
    *,
    cursors: dict[str, int] | None = None,
    prep_start: date | None = None,
    ordered_ids: dict[str, list[str]] | None = None,
    href_builder: Any | None = None,
    weak_tags_by_skill: dict[str, list[str]] | None = None,
    hub_tags_by_id: dict[str, list[str]] | None = None,
    user_id: UUID | str | None = None,
    progress_map: dict[str, dict[str, Any]] | None = None,
    hub_to_set: dict[str, str] | None = None,
    used_hub_ids: set[str] | None = None,
    used_set_ids: set[str] | None = None,
    today: date | None = None,
    source: str = "serve_fill",
    claim: bool = True,
    user_exam_module: str | None = None,
    hub_exam_module_by_id: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Preserve established assignments; fill only empty eligible slots uniquely."""
    del cursors, prep_start
    if not isinstance(study_plan, dict):
        return study_plan

    from app.practice.weakness import order_pool_for_weakness

    pools = ordered_ids if ordered_ids is not None else _ordered_ids()
    mapping = dict(hub_to_set or {})
    if not mapping:
        try:
            from app.practice.catalog import get_hub_set_ids

            mapping = dict(get_hub_set_ids())
        except Exception:
            mapping = {}

    tags_map = hub_tags_by_id
    if weak_tags_by_skill and tags_map is None:
        from app.practice.catalog import get_hub_skill_tags_by_id

        tags_map = get_hub_skill_tags_by_id()

    exam_map = hub_exam_module_by_id
    if exam_map is None:
        try:
            from app.practice.catalog import get_hub_exam_modules

            exam_map = get_hub_exam_modules()
        except Exception:
            exam_map = {}

    track = user_exam_module
    if track is None and user_id is not None:
        try:
            from app.payments.repository import get_user_exam_module

            track = get_user_exam_module(user_id)
        except Exception:
            track = None

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

    used_h, used_s = collect_used_assignment_ids(
        user_id=user_id,
        study_plan=study_plan,
        progress_map=progress_map,
        hub_to_set=mapping,
    )
    if used_hub_ids is not None:
        used_h |= used_hub_ids
    if used_set_ids is not None:
        used_s |= used_set_ids

    orphan_hubs_by_skill = _ledger_orphans_by_skill(
        user_id=user_id,
        study_plan=study_plan,
        assignable_by_skill=ordered_pools,
    )

    today_d = today or date.today()
    do_claim = bool(claim and user_id)
    new_fills: list[str] = []

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
    rewritten_days: dict[tuple[int, int], dict[str, Any]] = {}

    for wi, di, day in day_entries:
        day_date = _parse_plan_day(day.get("date"))
        if day_date is None:
            kind = "future"
        elif day_date < today_d:
            kind = "past"
        elif day_date == today_d:
            kind = "today"
        else:
            kind = "future"

        tasks_in = [t for t in (day.get("tasks") or []) if isinstance(t, dict)]
        hub_for_skill: dict[str, str | None] = {}
        skills_on_day = []
        for task in tasks_in:
            skill = str(task.get("module") or "").strip().lower()
            if skill in SKILLS and skill not in skills_on_day:
                skills_on_day.append(skill)

        for skill in skills_on_day:
            existing = _existing_hub_for_skill(tasks_in, skill)
            if _should_preserve_assignment(kind=kind, existing_hub=existing):
                hub_for_skill[skill] = existing
                if existing:
                    _mark_used(existing, str(mapping.get(existing) or ""), used_h, used_s)
                continue
            recovered = _pop_orphan_hub(orphan_hubs_by_skill, skill)
            if recovered:
                hub_for_skill[skill] = recovered
                _mark_used(recovered, str(mapping.get(recovered) or ""), used_h, used_s)
                new_fills.append(recovered)
                continue
            hub = pick_hub_for_slot(
                skill=skill,
                hub_ids=ordered_pools.get(skill) or [],
                used_hub_ids=used_h,
                used_set_ids=used_s,
                hub_to_set=mapping,
                user_id=user_id,
                source=source,
                assigned_on=day_date,
                claim=do_claim,
                user_exam_module=track,
                hub_exam_module_by_id=exam_map,
            )
            hub_for_skill[skill] = hub
            if hub:
                new_fills.append(hub)

        tasks_out: list[dict[str, Any]] = []
        for task in day.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            skill = str(task.get("module") or "").strip().lower()
            task_out = dict(task)
            if skill in SKILLS:
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

    weeks_out: list[dict[str, Any]] = []
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
            if hid and str(hid) not in assigned:
                assigned.append(str(hid))

    out = {**study_plan, "weeks": weeks_out, "assigned_hub_ids": assigned}
    if new_fills:
        out["_new_assignment_hub_ids"] = new_fills
    return out
