"""Ordered hub catalogue for plan assignment."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache

from app.practice import repository
from app.practice.assignment import assign_hub_for_day

SKILLS = repository.SKILLS
DIFFICULTY_RANK = repository.DIFFICULTY_RANK


@lru_cache(maxsize=1)
def _catalog_cache_key() -> int:
    """Bust cache by returning a static key; call clear_hub_catalog_cache() after seed changes."""
    return 1


def clear_hub_catalog_cache() -> None:
    get_ordered_hub_ids_by_skill.cache_clear()
    get_hub_submit_configs_by_id.cache_clear()
    get_hub_skill_tags_by_id.cache_clear()
    from app.practice.repository import clear_hub_list_cache

    clear_hub_list_cache()


@lru_cache(maxsize=1)
def get_ordered_hub_ids_by_skill() -> dict[str, list[str]]:
    """Assignable hubs only, ordered easy → medium → hard then catalogue order."""
    _catalog_cache_key()
    grouped = repository.list_assignable_hubs_grouped()
    result: dict[str, list[str]] = {}
    for skill in SKILLS:
        flat = [repository._flatten_hub_row(row) for row in grouped.get(skill, [])]
        flat.sort(
            key=lambda h: (
                DIFFICULTY_RANK.get(str(h.get("difficulty") or ""), 99),
                int(h.get("bank_number") or 0),
                int(h.get("set_number") or 0),
                int(h.get("sort_order") or 0),
            )
        )
        result[skill] = [h["id"] for h in flat]
    return result


@lru_cache(maxsize=1)
def get_hub_submit_configs_by_id() -> dict[str, dict]:
    """Map assignable hub id → submit_config (Phase 2 module targeting)."""
    _catalog_cache_key()
    grouped = repository.list_assignable_hubs_grouped()
    out: dict[str, dict] = {}
    for skill in SKILLS:
        for row in grouped.get(skill, []):
            flat = repository._flatten_hub_row(row)
            cfg = flat.get("submit_config")
            if isinstance(cfg, dict):
                out[str(flat["id"])] = cfg
            else:
                out[str(flat["id"])] = {}
    return out


@lru_cache(maxsize=1)
def get_hub_skill_tags_by_id() -> dict[str, list[str]]:
    """Map assignable hub id → skill_tags from bank_questions + bank weakness_tags."""
    _catalog_cache_key()
    from app.db.supabase_client import get_supabase
    from app.practice.weakness import dominant_tags_from_counter, normalize_tag

    grouped = repository.list_assignable_hubs_grouped()
    set_to_hubs: dict[str, list[str]] = {}
    bank_tags: dict[str, list[str]] = {}
    for skill in SKILLS:
        for row in grouped.get(skill, []):
            flat = repository._flatten_hub_row(row)
            hid = str(flat["id"])
            set_id = str(flat.get("set_id") or "")
            if set_id:
                set_to_hubs.setdefault(set_id, []).append(hid)
            sets = row.get("practice_sets") or {}
            if isinstance(sets, list):
                sets = sets[0] if sets else {}
            banks = (sets.get("practice_banks") if isinstance(sets, dict) else None) or {}
            if isinstance(banks, list):
                banks = banks[0] if banks else {}
            raw_tags = banks.get("weakness_tags") if isinstance(banks, dict) else None
            if isinstance(raw_tags, list):
                bank_tags[hid] = [normalize_tag(t) for t in raw_tags if t]

    set_ids = list(set_to_hubs.keys())
    counters: dict[str, Counter[str]] = {sid: Counter() for sid in set_ids}
    if set_ids:
        sb = get_supabase()
        sections = (
            sb.table("bank_sections")
            .select("id, practice_set_id")
            .in_("practice_set_id", set_ids)
            .execute()
        ).data or []
        sec_to_set = {str(s["id"]): str(s["practice_set_id"]) for s in sections}
        sec_ids = list(sec_to_set.keys())
        for i in range(0, len(sec_ids), 80):
            chunk = sec_ids[i : i + 80]
            qrows = (
                sb.table("bank_questions")
                .select("section_id, skill_tag, question_type")
                .in_("section_id", chunk)
                .execute()
            ).data or []
            for q in qrows:
                sid = sec_to_set.get(str(q.get("section_id") or ""))
                if not sid:
                    continue
                tag = normalize_tag(q.get("skill_tag") or q.get("question_type"))
                if tag:
                    counters[sid][tag] += 1

    out: dict[str, list[str]] = {}
    for set_id, hubs in set_to_hubs.items():
        dom = dominant_tags_from_counter(counters.get(set_id) or Counter())
        for hid in hubs:
            merged: list[str] = []
            seen: set[str] = set()
            for t in list(dom) + list(bank_tags.get(hid) or []):
                if not t or t in seen:
                    continue
                if t in ("phase0", "general") or t.startswith("phase0") or "_bank_" in t:
                    continue
                seen.add(t)
                merged.append(t)
            out[hid] = merged
    return out


def pick_hub_for_slot(
    *,
    skill: str,
    day_index: int,
    slot_index: int = 0,
    completed_count: int | None = None,
    previous_hub_id: str | None = None,
    weak_tags: list[str] | None = None,
) -> str | None:
    """Pick a hub via soft-repeat; prefer weakness-matching hubs when tags given."""
    del slot_index
    from app.practice.weakness import order_pool_for_weakness

    hub_ids = get_ordered_hub_ids_by_skill().get(skill) or []
    if weak_tags:
        hub_ids = order_pool_for_weakness(
            hub_ids,
            weak_tags=weak_tags,
            hub_tags_by_id=get_hub_skill_tags_by_id(),
        )
    cursor = int(completed_count) if completed_count is not None else 0
    return assign_hub_for_day(
        hub_ids=hub_ids,
        cursor=cursor,
        day_offset=max(int(day_index), 0),
        previous_hub_id=previous_hub_id,
    )
