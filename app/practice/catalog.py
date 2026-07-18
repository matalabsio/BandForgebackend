"""Ordered hub catalogue for plan assignment."""

from __future__ import annotations

from functools import lru_cache

from app.practice import repository

SKILLS = repository.SKILLS


@lru_cache(maxsize=1)
def _catalog_cache_key() -> int:
    """Bust cache by returning a static key; call clear_hub_catalog_cache() after seed changes."""
    return 1


def clear_hub_catalog_cache() -> None:
    get_ordered_hub_ids_by_skill.cache_clear()


def get_ordered_hub_ids_by_skill() -> dict[str, list[str]]:
    _catalog_cache_key()
    grouped = repository.list_all_hubs_grouped()
    result: dict[str, list[str]] = {}
    for skill in SKILLS:
        flat = [repository._flatten_hub_row(row) for row in grouped.get(skill, [])]
        flat.sort(key=lambda h: (h["bank_number"], h["set_number"], h["sort_order"]))
        result[skill] = [h["id"] for h in flat]
    return result


def pick_hub_for_slot(*, skill: str, day_index: int, slot_index: int) -> str | None:
    """Round-robin hub assignment by calendar day and session slot."""
    hub_ids = get_ordered_hub_ids_by_skill().get(skill) or []
    if not hub_ids:
        return None
    idx = (day_index * 10 + slot_index) % len(hub_ids)
    return hub_ids[idx]
