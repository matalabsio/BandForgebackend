"""Ordered hub catalogue for plan assignment."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache

from app.practice import repository
from app.practice.assignment_ledger import is_question_bank_hub

SKILLS = repository.SKILLS
DIFFICULTY_RANK = repository.DIFFICULTY_RANK


@lru_cache(maxsize=1)
def _catalog_cache_key() -> int:
    """Bust cache by returning a static key; call clear_hub_catalog_cache() after seed changes."""
    return 1


def clear_hub_catalog_cache() -> None:
    get_ordered_hub_ids_by_skill.cache_clear()
    get_ordered_question_bank_ids_by_skill.cache_clear()
    get_hub_set_ids.cache_clear()
    get_hub_exam_modules.cache_clear()
    get_hub_submit_configs_by_id.cache_clear()
    get_hub_skill_tags_by_id.cache_clear()
    from app.practice.repository import clear_hub_list_cache

    clear_hub_list_cache()


def _sorted_assignable_flats(skill: str) -> list[dict]:
    grouped = repository.list_assignable_hubs_grouped()
    flats = [repository._flatten_hub_row(row) for row in grouped.get(skill, [])]
    flats.sort(
        key=lambda h: (
            DIFFICULTY_RANK.get(str(h.get("difficulty") or ""), 99),
            int(h.get("bank_number") or 0),
            int(h.get("set_number") or 0),
            int(h.get("sort_order") or 0),
            str(h.get("set_id") or ""),
            str(h.get("id") or ""),
        )
    )
    return flats


@lru_cache(maxsize=1)
def get_ordered_hub_ids_by_skill() -> dict[str, list[str]]:
    """Assignable hubs only, ordered easy → medium → hard then catalogue order."""
    _catalog_cache_key()
    result: dict[str, list[str]] = {}
    for skill in SKILLS:
        result[skill] = [h["id"] for h in _sorted_assignable_flats(skill)]
    return result


@lru_cache(maxsize=1)
def get_ordered_question_bank_ids_by_skill() -> dict[str, list[str]]:
    """Assignable Question Bank hubs only (excludes Mock / Phase-0 module hubs)."""
    _catalog_cache_key()
    grouped = repository.list_assignable_hubs_grouped()
    result: dict[str, list[str]] = {}
    for skill in SKILLS:
        rows = grouped.get(skill, [])
        flats = []
        for row, flat in zip(rows, [repository._flatten_hub_row(r) for r in rows]):
            if not is_question_bank_hub(row) and not is_question_bank_hub(flat):
                continue
            flats.append(flat)
        flats.sort(
            key=lambda h: (
                DIFFICULTY_RANK.get(str(h.get("difficulty") or ""), 99),
                int(h.get("bank_number") or 0),
                int(h.get("set_number") or 0),
                int(h.get("sort_order") or 0),
                str(h.get("set_id") or ""),
                str(h.get("id") or ""),
            )
        )
        result[skill] = [h["id"] for h in flats]
    return result


@lru_cache(maxsize=1)
def get_hub_set_ids() -> dict[str, str]:
    """Assignable hub_id → practice_set_id."""
    _catalog_cache_key()
    out: dict[str, str] = {}
    grouped = repository.list_assignable_hubs_grouped()
    for skill in SKILLS:
        for row in grouped.get(skill, []):
            flat = repository._flatten_hub_row(row)
            hid = str(flat.get("id") or "")
            sid = str(flat.get("set_id") or "")
            if hid and sid:
                out[hid] = sid
    return out


@lru_cache(maxsize=1)
def get_hub_exam_modules() -> dict[str, str | None]:
    """Assignable hub_id → practice_sets.exam_module (academic|general_training|both|None)."""
    _catalog_cache_key()
    out: dict[str, str | None] = {}
    grouped = repository.list_assignable_hubs_grouped()
    for skill in SKILLS:
        for row in grouped.get(skill, []):
            flat = repository._flatten_hub_row(row)
            hid = str(flat.get("id") or "")
            if not hid:
                continue
            raw = flat.get("exam_module")
            if raw is None:
                out[hid] = None
            else:
                text = str(raw).strip().lower()
                out[hid] = text or None
    return out


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
    day_index: int = 0,
    slot_index: int = 0,
    completed_count: int | None = None,
    previous_hub_id: str | None = None,
    weak_tags: list[str] | None = None,
    used_hub_ids: set[str] | None = None,
    used_set_ids: set[str] | None = None,
    hub_to_set: dict[str, str] | None = None,
    hub_ids: list[str] | None = None,
    user_id=None,
    source: str = "plan_generate",
    assigned_on=None,
    claim: bool = False,
    hub_tags_by_id: dict[str, list[str]] | None = None,
    user_exam_module: str | None = None,
    hub_exam_module_by_id: dict[str, str | None] | None = None,
) -> str | None:
    """Unique unused Question Bank pick. Never wraps."""
    from app.practice.assignment import pick_hub_for_slot as pick_unique

    ids = hub_ids
    if ids is None:
        ids = get_ordered_question_bank_ids_by_skill().get(skill) or []
    mapping = hub_to_set
    if mapping is None:
        try:
            mapping = get_hub_set_ids()
        except Exception:
            mapping = {}
    tags = hub_tags_by_id
    if weak_tags and tags is None:
        tags = get_hub_skill_tags_by_id()
    exam_map = hub_exam_module_by_id
    if skill == "writing" and exam_map is None:
        try:
            exam_map = get_hub_exam_modules()
        except Exception:
            exam_map = {}
    return pick_unique(
        skill=skill,
        day_index=day_index,
        slot_index=slot_index,
        completed_count=completed_count,
        previous_hub_id=previous_hub_id,
        hub_ids=ids,
        weak_tags=weak_tags,
        hub_tags_by_id=tags,
        used_hub_ids=used_hub_ids,
        used_set_ids=used_set_ids,
        hub_to_set=mapping,
        user_id=user_id,
        source=source,
        assigned_on=assigned_on,
        claim=claim,
        user_exam_module=user_exam_module,
        hub_exam_module_by_id=exam_map,
    )
