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


@lru_cache(maxsize=1)
def get_ordered_hub_ids_by_skill() -> dict[str, list[str]]:
    _catalog_cache_key()
    grouped = repository.list_all_hubs_grouped()
    result: dict[str, list[str]] = {}
    for skill in SKILLS:
        flat = [repository._flatten_hub_row(row) for row in grouped.get(skill, [])]
        flat.sort(key=lambda h: (h["bank_number"], h["set_number"], h["sort_order"]))
        result[skill] = [h["id"] for h in flat]
    return result


def pick_hub_for_slot(
    *,
    skill: str,
    day_index: int,
    slot_index: int = 0,
    completed_count: int | None = None,
) -> str | None:
    """Pick a hub for a plan day.

    When ``completed_count`` is provided, assignment is progress-aware:
    day 0 → current incomplete hub index, day N projects forward from there.
    ``slot_index`` is ignored for catalogue offset (skills share day stacks).
    """
    hub_ids = get_ordered_hub_ids_by_skill().get(skill) or []
    if not hub_ids:
        return None
    if completed_count is not None:
        idx = min(max(int(completed_count), 0) + max(int(day_index), 0), len(hub_ids) - 1)
        return hub_ids[idx]
    # Legacy fallback (no user progress): advance by day only
    idx = max(int(day_index), 0) % len(hub_ids)
    return hub_ids[idx]
