"""Durable Question Bank assignment ledger (personalized plans).

Records that a user was given a practice set/hub. Completions stay on
user_hub_progress. Unique picker claims rows via try_claim_practice_assignment.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError

from app.practice.repository import SKILLS, _exec, _flatten_hub_row, get_supabase

QUESTION_BANK_CUSTOM_BANK_NUMBER = 5
ASSIGNMENT_SOURCES = frozenset(
    {"plan_generate", "publish_fill", "replan", "serve_fill"}
)

_HUB_LEDGER_COLUMNS = (
    "id, slug, set_id, submit_config, "
    "practice_sets!inner(id, set_number, status, practice_banks!inner(skill, bank_number))"
)


def is_question_bank_hub(row: dict[str, Any] | None) -> bool:
    """True for Admin Question Bank hubs, not Mock-library questions."""
    if not row:
        return False
    flat = _flatten_hub_row(row) if "practice_sets" in row or "set_id" in row else row
    if int(flat.get("bank_number") or 0) >= QUESTION_BANK_CUSTOM_BANK_NUMBER:
        return True
    cfg = flat.get("submit_config") or row.get("submit_config") or {}
    if isinstance(cfg, dict) and str(cfg.get("type") or "").strip().lower() == "bank":
        return True
    return False


def hub_ids_from_study_plan(study_plan: dict[str, Any] | None) -> list[str]:
    """Unique hub ids from assigned_hub_ids and task hub_id fields, first-seen order."""
    if not isinstance(study_plan, dict):
        return []
    seen: set[str] = set()
    out: list[str] = []

    def _add(raw: Any) -> None:
        hid = str(raw or "").strip()
        if not hid or hid in seen:
            return
        seen.add(hid)
        out.append(hid)

    for raw in study_plan.get("assigned_hub_ids") or []:
        _add(raw)
    for week in study_plan.get("weeks") or []:
        if not isinstance(week, dict):
            continue
        for day in week.get("days") or []:
            if not isinstance(day, dict):
                continue
            for task in day.get("tasks") or []:
                if isinstance(task, dict):
                    _add(task.get("hub_id"))
    return out


def _load_hubs_by_id(hub_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = [h for h in hub_ids if h]
    if not ids:
        return {}
    sb = get_supabase()
    rows = (
        _exec(
            sb.table("practice_hubs")
            .select(_HUB_LEDGER_COLUMNS)
            .in_("id", ids)
        )
    ).data or []
    return {str(r["id"]): r for r in rows if r.get("id")}


def record_practice_assignments(
    *,
    user_id: UUID | str,
    hub_ids: list[str],
    source: str,
    assigned_on: date | str | None = None,
) -> int:
    """Insert ledger rows for Question Bank hubs. Idempotent; never replaces.

    Returns the number of rows sent to upsert (QB hubs only). Unique
    conflicts are ignored. Non-QB / unknown ids are skipped.
    """
    src = str(source or "").strip()
    if src not in ASSIGNMENT_SOURCES:
        raise ValueError(f"invalid assignment source: {source!r}")
    unique_ids = list(dict.fromkeys(str(h).strip() for h in hub_ids if str(h).strip()))
    if not unique_ids:
        return 0

    on_date: str
    if assigned_on is None:
        on_date = date.today().isoformat()
    elif isinstance(assigned_on, date):
        on_date = assigned_on.isoformat()
    else:
        on_date = str(assigned_on)[:10]

    hubs = _load_hubs_by_id(unique_ids)
    payloads: list[dict[str, Any]] = []
    seen_sets: set[str] = set()
    for hid in unique_ids:
        row = hubs.get(hid)
        if not is_question_bank_hub(row):
            continue
        flat = _flatten_hub_row(row)
        skill = str(flat.get("skill") or "").strip().lower()
        set_id = str(flat.get("set_id") or "").strip()
        if skill not in SKILLS or not set_id:
            continue
        if set_id in seen_sets:
            continue
        seen_sets.add(set_id)
        payloads.append(
            {
                "user_id": str(user_id),
                "hub_id": hid,
                "practice_set_id": set_id,
                "skill": skill,
                "assigned_on": on_date,
                "source": src,
            }
        )
    if not payloads:
        return 0
    _insert_assignment_payloads(payloads)
    return len(payloads)


def _is_unique_violation(exc: BaseException) -> bool:
    code = str(getattr(exc, "code", "") or "")
    if code == "23505":
        return True
    msg = str(exc).lower()
    return "duplicate key" in msg or "unique constraint" in msg


def _upsert_ignore(sb: Any, rows: list[dict[str, Any]]) -> None:
    _exec(
        sb.table("user_practice_assignments").upsert(
            rows,
            on_conflict="user_id,hub_id",
            ignore_duplicates=True,
        )
    )


def _insert_assignment_payloads(payloads: list[dict[str, Any]]) -> None:
    """Insert without replacing existing rows. Ignore hub or set uniqueness conflicts."""
    sb = get_supabase()
    try:
        _upsert_ignore(sb, payloads)
        return
    except APIError as exc:
        if not _is_unique_violation(exc):
            raise
    for row in payloads:
        try:
            _upsert_ignore(sb, [row])
        except APIError as inner:
            if not _is_unique_violation(inner):
                raise


def list_user_assignment_ids(
    user_id: UUID | str,
) -> tuple[set[str], set[str]]:
    """Return (hub_ids, practice_set_ids) already in the ledger for this user."""
    sb = get_supabase()
    rows = (
        _exec(
            sb.table("user_practice_assignments")
            .select("hub_id, practice_set_id")
            .eq("user_id", str(user_id))
        )
    ).data or []
    hubs: set[str] = set()
    sets: set[str] = set()
    for row in rows:
        hid = str(row.get("hub_id") or "").strip()
        sid = str(row.get("practice_set_id") or "").strip()
        if hid:
            hubs.add(hid)
        if sid:
            sets.add(sid)
    return hubs, sets


def list_user_assignment_rows(user_id: UUID | str) -> list[dict[str, Any]]:
    """Ledger rows for diagnostics and crash-recovery orphan placement."""
    sb = get_supabase()
    rows = (
        _exec(
            sb.table("user_practice_assignments")
            .select("hub_id, practice_set_id, skill, source, assigned_on")
            .eq("user_id", str(user_id))
        )
    ).data or []
    return [row for row in rows if isinstance(row, dict)]


def try_claim_practice_assignment(
    *,
    user_id: UUID | str,
    hub_id: str,
    practice_set_id: str,
    skill: str,
    source: str,
    assigned_on: date | str | None = None,
) -> str:
    """Insert one ledger row. Returns claimed | already | conflict.

    ``claimed`` — this caller inserted the row.
    ``already`` — this user already owns this hub (retry of the same assignment).
    ``conflict`` — this user already owns the set or hub via a different row.
    Never replaces an existing row.
    """
    src = str(source or "").strip()
    if src not in ASSIGNMENT_SOURCES:
        raise ValueError(f"invalid assignment source: {source!r}")
    skill_n = str(skill or "").strip().lower()
    if skill_n not in SKILLS:
        return "conflict"
    hid = str(hub_id or "").strip()
    sid = str(practice_set_id or "").strip()
    if not hid or not sid:
        return "conflict"
    if assigned_on is None:
        on_date = date.today().isoformat()
    elif isinstance(assigned_on, date):
        on_date = assigned_on.isoformat()
    else:
        on_date = str(assigned_on)[:10]
    payload = {
        "user_id": str(user_id),
        "hub_id": hid,
        "practice_set_id": sid,
        "skill": skill_n,
        "assigned_on": on_date,
        "source": src,
    }
    sb = get_supabase()
    try:
        _exec(sb.table("user_practice_assignments").insert(payload))
        return "claimed"
    except APIError as exc:
        if not _is_unique_violation(exc):
            raise
    existing = (
        _exec(
            sb.table("user_practice_assignments")
            .select("hub_id, practice_set_id")
            .eq("user_id", str(user_id))
        )
    ).data or []
    for row in existing:
        if str(row.get("hub_id") or "") == hid:
            return "already"
        if str(row.get("practice_set_id") or "") == sid:
            return "conflict"
    return "conflict"


def record_assignments_from_study_plan(
    *,
    user_id: UUID | str,
    study_plan: dict[str, Any] | None,
    source: str,
    assigned_on: date | str | None = None,
) -> int:
    """Record QB hubs already placed on a persisted personalized plan."""
    on = assigned_on
    if on is None and isinstance(study_plan, dict):
        raw = study_plan.get("prep_start")
        if raw:
            on = str(raw)[:10]
    return record_practice_assignments(
        user_id=user_id,
        hub_ids=hub_ids_from_study_plan(study_plan),
        source=source,
        assigned_on=on,
    )


def backfill_practice_assignments(
    *,
    profiles: list[dict[str, Any]],
    progress_rows: list[dict[str, Any]],
    attempt_rows: list[dict[str, Any]] | None = None,
) -> int:
    """Idempotent in-process backfill used by tests; production uses the SQL migration.

    ``profiles``: user_learning_profiles rows with user_id + study_plan.
    ``progress_rows``: user_hub_progress rows with user_id + hub_id.
    ``attempt_rows``: practice_exercise_attempts with user_id + hub_id.
    """
    inserted = 0
    for row in profiles:
        uid = row.get("user_id")
        if not uid:
            continue
        inserted += record_assignments_from_study_plan(
            user_id=str(uid),
            study_plan=row.get("study_plan") if isinstance(row.get("study_plan"), dict) else {},
            source="plan_generate",
        )
    for src_rows, source in (
        (progress_rows, "serve_fill"),
        (attempt_rows or [], "serve_fill"),
    ):
        by_user: dict[str, list[str]] = {}
        for prow in src_rows:
            uid = str(prow.get("user_id") or "")
            hid = str(prow.get("hub_id") or "")
            if uid and hid:
                by_user.setdefault(uid, []).append(hid)
        for uid, hubs in by_user.items():
            inserted += record_practice_assignments(
                user_id=uid,
                hub_ids=hubs,
                source=source,
            )
    return inserted
