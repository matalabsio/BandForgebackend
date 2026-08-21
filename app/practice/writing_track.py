"""FSP Writing track content filter (users.exam_module × practice_sets.exam_module).

Applies ONLY to skill=writing on the FSP personalized-plan path.
Listening / Reading / Speaking are never filtered here.
Writing Skill packs continue to use user_program_usage.exam_module.
"""

from __future__ import annotations

from typing import Iterable

VALID_USER_EXAM_MODULES = frozenset({"academic", "general_training"})
VALID_SET_EXAM_MODULES = frozenset({"academic", "general_training", "both"})

WRITING_TRACK_REQUIRED_DETAIL = (
    "Writing module must be selected before Writing practice can be assigned"
)


def normalize_user_exam_module(value: object) -> str | None:
    """Return academic | general_training | None (NULL / invalid → None)."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in VALID_USER_EXAM_MODULES:
        return text
    return None


def normalize_set_exam_module(value: object) -> str | None:
    """Return academic | general_training | both | None for a practice set tag."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in VALID_SET_EXAM_MODULES:
        return text
    return None


def writing_set_compatible_with_user(
    *,
    set_exam_module: object,
    user_exam_module: object,
) -> bool:
    """True when a Writing practice set may be newly assigned to this FSP user.

    Rules:
    - user NULL / invalid → never compatible (do not assume Academic)
    - set ``both`` → compatible with academic or general_training users
    - set academic / general_training → only matching user
    - set NULL / unclassified → not compatible (explicit tag required)
    """
    user = normalize_user_exam_module(user_exam_module)
    if user is None:
        return False
    set_mod = normalize_set_exam_module(set_exam_module)
    if set_mod is None:
        return False
    if set_mod == "both":
        return True
    return set_mod == user


def filter_writing_hub_ids(
    hub_ids: Iterable[str],
    *,
    hub_exam_module_by_id: dict[str, str | None] | None,
    user_exam_module: object,
) -> list[str]:
    """Keep Writing hubs whose practice_sets.exam_module matches the user track.

    When user_exam_module is NULL, returns [] (no new Writing assignment).
    Missing map entries are treated as unclassified (excluded).
    """
    user = normalize_user_exam_module(user_exam_module)
    if user is None:
        return []
    mapping = hub_exam_module_by_id or {}
    out: list[str] = []
    for hid in hub_ids:
        key = str(hid or "").strip()
        if not key:
            continue
        if writing_set_compatible_with_user(
            set_exam_module=mapping.get(key),
            user_exam_module=user,
        ):
            out.append(key)
    return out


def fsp_writing_track_ready(user_exam_module: object) -> bool:
    """True when the FSP user may receive new Writing hub assignments."""
    return normalize_user_exam_module(user_exam_module) is not None
