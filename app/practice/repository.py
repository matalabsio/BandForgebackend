"""Supabase accessors for practice hubs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.db.supabase_client import execute_with_retry, get_supabase

SKILLS = ("listening", "reading", "writing", "speaking")
VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard"})
DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}

HUB_LIST_COLUMNS = (
    "id, slug, set_id, estimated_min, sort_order, practice_prompt, submit_config, "
    "practice_sets!inner("
    "id, set_number, title, status, difficulty, "
    "practice_banks!inner(skill, bank_number, title, weakness_tags)"
    ")"
)

HUB_DETAIL_COLUMNS = (
    "id, slug, set_id, videos, practice_prompt, submit_config, estimated_min, sort_order, "
    "practice_sets!inner("
    "id, set_number, title, status, difficulty, "
    "practice_banks!inner(skill, bank_number, title, weakness_tags)"
    ")"
)


def _exec(query):
    return execute_with_retry(query.execute)


def _set_content_ok(*, skill: str, sections: list[dict[str, Any]], questions_by_section: dict[str, list[dict[str, Any]]]) -> bool:
    """Return True when a practice set meets Phase-0 assignable content rules."""
    skill = str(skill or "").strip().lower()
    if not sections:
        return False

    all_questions: list[dict[str, Any]] = []
    for sec in sections:
        sid = str(sec.get("id") or "")
        all_questions.extend(questions_by_section.get(sid) or [])

    if skill == "listening":
        if not all_questions:
            return False
        for sec in sections:
            audio = str(sec.get("audio_key") or "").strip()
            sid = str(sec.get("id") or "")
            sec_qs = questions_by_section.get(sid) or []
            if not sec_qs:
                continue
            if not audio and not any(str(q.get("audio_url") or "").strip() for q in sec_qs):
                return False
            for q in sec_qs:
                if not str(q.get("correct_answer") or "").strip():
                    return False
        return True

    if skill == "reading":
        if not all_questions:
            return False
        has_passage = any(str(s.get("passage_text") or "").strip() for s in sections) or any(
            str(q.get("passage_text") or "").strip() for q in all_questions
        )
        if not has_passage:
            return False
        for q in all_questions:
            if not str(q.get("correct_answer") or "").strip():
                return False
        return True

    if skill == "writing":
        for sec in sections:
            if str(sec.get("passage_text") or "").strip():
                return True
        return any(str(q.get("prompt") or "").strip() for q in all_questions)

    if skill == "speaking":
        return any(str(q.get("prompt") or "").strip() for q in all_questions)

    return False


def _assignable_set_ids(set_ids: list[str], skill_by_set: dict[str, str]) -> set[str]:
    """Which practice_set ids pass published-content gates (batch)."""
    if not set_ids:
        return set()
    sb = get_supabase()
    sections = (
        sb.table("bank_sections")
        .select("id, practice_set_id, module, part, audio_key, passage_text")
        .in_("practice_set_id", set_ids)
        .execute()
    ).data or []
    section_ids = [str(s["id"]) for s in sections if s.get("id")]
    questions: list[dict[str, Any]] = []
    if section_ids:
        questions = (
            sb.table("bank_questions")
            .select("id, section_id, prompt, passage_text, audio_url, correct_answer")
            .in_("section_id", section_ids)
            .execute()
        ).data or []

    sections_by_set: dict[str, list[dict[str, Any]]] = {sid: [] for sid in set_ids}
    for sec in sections:
        sid = str(sec.get("practice_set_id") or "")
        if sid in sections_by_set:
            sections_by_set[sid].append(sec)

    questions_by_section: dict[str, list[dict[str, Any]]] = {}
    for q in questions:
        sec_id = str(q.get("section_id") or "")
        questions_by_section.setdefault(sec_id, []).append(q)

    ok: set[str] = set()
    for sid in set_ids:
        skill = skill_by_set.get(sid) or ""
        if _set_content_ok(
            skill=skill,
            sections=sections_by_set.get(sid) or [],
            questions_by_section=questions_by_section,
        ):
            ok.add(sid)
    return ok


def _filter_assignable_hub_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only published, difficulty-tagged hubs with valid bank content."""
    candidates: list[dict[str, Any]] = []
    set_ids: list[str] = []
    skill_by_set: dict[str, str] = {}
    for row in rows:
        flat = _flatten_hub_row(row)
        status = str(flat.get("status") or "").strip().lower()
        difficulty = str(flat.get("difficulty") or "").strip().lower()
        set_id = str(flat.get("set_id") or "")
        skill = str(flat.get("skill") or "")
        if status != "published":
            continue
        if difficulty not in VALID_DIFFICULTIES:
            continue
        if not set_id or skill not in SKILLS:
            continue
        candidates.append(row)
        if set_id not in skill_by_set:
            set_ids.append(set_id)
            skill_by_set[set_id] = skill

    if not candidates:
        return []

    ready = _assignable_set_ids(set_ids, skill_by_set)
    return [
        row
        for row in candidates
        if str(_flatten_hub_row(row).get("set_id") or "") in ready
    ]


def is_hub_assignable(row: dict[str, Any] | None) -> bool:
    """True when a hub detail row is safe to serve to students."""
    if not row:
        return False
    return bool(_filter_assignable_hub_rows([row]))


def list_hubs_for_skill(skill: str) -> list[dict[str, Any]]:
    """Student-facing hubs for one skill (published + content-valid only)."""
    from app.cache.hybrid_cache import get_json, set_json

    cache_key = f"practice:hubs:list:assignable:{skill}"
    cached = get_json(cache_key)
    if isinstance(cached, list):
        return cached
    sb = get_supabase()
    result = (
        sb.table("practice_hubs")
        .select(HUB_LIST_COLUMNS)
        .eq("practice_sets.practice_banks.skill", skill)
        .eq("practice_sets.status", "published")
        .order("sort_order")
        .execute()
    )
    rows = _filter_assignable_hub_rows(list(result.data or []))
    rows.sort(
        key=lambda r: (
            DIFFICULTY_RANK.get(str(_flatten_hub_row(r).get("difficulty") or ""), 99),
            int(_flatten_hub_row(r).get("bank_number") or 0),
            int(_flatten_hub_row(r).get("set_number") or 0),
            int(_flatten_hub_row(r).get("sort_order") or 0),
        )
    )
    set_json(cache_key, rows, 60)
    return rows


def list_all_hubs_grouped() -> dict[str, list[dict[str, Any]]]:
    """Assignable hubs only, grouped by skill (student catalogue)."""
    return list_assignable_hubs_grouped()


def list_assignable_hubs_grouped() -> dict[str, list[dict[str, Any]]]:
    """One hubs query + content filter, group by skill.

    Practice pool is published, content-valid hubs only (Phase 0 MT1/MT2
    seeds). Diagnostic mocks never appear here — they have no practice hubs
    and student mock catalog excludes ``is_diagnostic``.
    """
    from app.cache.hybrid_cache import get_json, set_json

    cache_key = "practice:hubs:assignable_grouped"
    cached = get_json(cache_key)
    if isinstance(cached, dict) and all(s in cached for s in SKILLS):
        return {s: list(cached.get(s) or []) for s in SKILLS}

    sb = get_supabase()
    result = (
        sb.table("practice_hubs")
        .select(HUB_LIST_COLUMNS)
        .eq("practice_sets.status", "published")
        .order("sort_order")
        .execute()
    )
    filtered = _filter_assignable_hub_rows(list(result.data or []))
    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in SKILLS}
    for row in filtered:
        flat = _flatten_hub_row(row)
        skill = str(flat.get("skill") or "")
        if skill in grouped:
            grouped[skill].append(row)
    for skill in SKILLS:
        grouped[skill].sort(
            key=lambda r: (
                DIFFICULTY_RANK.get(str(_flatten_hub_row(r).get("difficulty") or ""), 99),
                int(_flatten_hub_row(r).get("bank_number") or 0),
                int(_flatten_hub_row(r).get("set_number") or 0),
                int(_flatten_hub_row(r).get("sort_order") or 0),
            )
        )
    set_json(cache_key, grouped, 60)
    return grouped


def clear_hub_list_cache() -> None:
    from app.cache.hybrid_cache import delete_many, invalidate_prefix

    delete_many(
        [
            "practice:hubs:all_grouped",
            "practice:hubs:assignable_grouped",
        ]
    )
    invalidate_prefix("practice:hubs:list:")


def get_hub_by_id(hub_id: str | UUID) -> dict[str, Any] | None:
    from app.cache.hybrid_cache import get_json, set_json

    cache_key = f"practice:hub:detail:{hub_id}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        if cached.get("__miss__"):
            return None
        return cached
    sb = get_supabase()
    result = (
        sb.table("practice_hubs")
        .select(HUB_DETAIL_COLUMNS)
        .eq("id", str(hub_id))
        .limit(1)
        .execute()
    )
    rows = result.data or []
    row = rows[0] if rows else None
    if row is None:
        set_json(cache_key, {"__miss__": True}, 30)
    else:
        set_json(cache_key, row, 60)
    return row


def get_user_progress_map(user_id: UUID) -> dict[str, dict[str, Any]]:
    from app.cache.hybrid_cache import get_json, set_json

    cache_key = f"practice:progress:{user_id}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        return {str(k): v for k, v in cached.items() if isinstance(v, dict)}

    sb = get_supabase()
    result = (
        sb.table("user_hub_progress")
        .select("hub_id, status, completed_at")
        .eq("user_id", str(user_id))
        .execute()
    )
    out = {str(row["hub_id"]): row for row in (result.data or [])}
    set_json(cache_key, out, 30)
    return out


def invalidate_user_progress_cache(user_id: UUID | str) -> None:
    from app.cache.hybrid_cache import delete_many

    delete_many(
        [
            f"practice:progress:{user_id}",
            f"learning:profile:{user_id}",
        ]
    )
    # Rewritten-plan keys use fingerprint suffix — wipe by prefix when available
    try:
        from app.cache.hybrid_cache import invalidate_prefix

        invalidate_prefix(f"learning:plan_rewritten:{user_id}:")
    except Exception:
        pass


def upsert_hub_completed(*, user_id: UUID, hub_id: str | UUID) -> dict[str, Any]:
    sb = get_supabase()
    now = datetime.now(UTC).isoformat()
    payload = {
        "user_id": str(user_id),
        "hub_id": str(hub_id),
        "status": "completed",
        "completed_at": now,
        "updated_at": now,
    }
    result = _exec(
        sb.table("user_hub_progress").upsert(
            payload,
            on_conflict="user_id,hub_id",
        )
    )
    invalidate_user_progress_cache(user_id)
    rows = result.data or []
    if rows:
        return rows[0]
    read = (
        sb.table("user_hub_progress")
        .select("*")
        .eq("user_id", str(user_id))
        .eq("hub_id", str(hub_id))
        .limit(1)
        .execute()
    )
    return (read.data or [{}])[0]


def count_completed_for_skill(*, user_id: UUID, skill: str) -> int:
    hubs = list_hubs_for_skill(skill)
    if not hubs:
        return 0
    hub_ids = [str(h["id"]) for h in hubs]
    progress = get_user_progress_map(user_id)
    return sum(
        1
        for hid in hub_ids
        if progress.get(hid, {}).get("status") == "completed"
    )


def get_skill_full_mock(skill: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("skill_full_mocks")
        .select("skill, mock_test_id, unlock_requires_sets")
        .eq("skill", skill)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def list_skill_full_mocks() -> list[dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("skill_full_mocks").select("*").execute()
    return list(result.data or [])


def _flatten_hub_row(row: dict[str, Any]) -> dict[str, Any]:
    sets = row.get("practice_sets") or {}
    if isinstance(sets, list):
        sets = sets[0] if sets else {}
    banks = sets.get("practice_banks") or {}
    if isinstance(banks, list):
        banks = banks[0] if banks else {}
    return {
        "id": str(row["id"]),
        "slug": row.get("slug") or "",
        "set_id": str(row.get("set_id") or sets.get("id") or ""),
        "skill": banks.get("skill") or "",
        "bank_number": int(banks.get("bank_number") or 0),
        "set_number": int(sets.get("set_number") or 0),
        "title": sets.get("title") or row.get("slug") or "",
        "status": str(sets.get("status") or "draft"),
        "difficulty": str(sets.get("difficulty") or "medium"),
        "estimated_min": int(row.get("estimated_min") or 25),
        "sort_order": int(row.get("sort_order") or 0),
        "videos": row.get("videos") or [],
        "practice_prompt": row.get("practice_prompt") or "",
        "submit_config": row.get("submit_config") or {},
    }
