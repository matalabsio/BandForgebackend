"""Admin question bank — standalone L/R/W/S content linked to practice_sets."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from postgrest.exceptions import APIError

from app.admin.answer_format import (
    expand_choose_two_rows,
    join_answers,
    looks_like_choose_two_pair,
    parse_choose_two_letters,
    split_answers,
)
from app.admin.audit import log_admin_action
from app.admin.stream_videos import videos_for_skill
from app.admin.listening_question_types import (
    MCQ_CHOOSE_TWO_UI,
    listening_to_display,
    listening_to_slug,
)
from app.admin.question_types import to_slug
from app.admin.schemas import (
    BankListeningPartResponse,
    BankReadingPartResponse,
    BankSpeakingPartResponse,
    BankWritingPartResponse,
    ListeningBuilderQuestionOut,
    ListeningBuilderSaveRequest,
    ListeningBuilderSaveResponse,
    PatchQuestionBankSetRequest,
    PatchQuestionBankSetResponse,
    PatchQuestionBankSetStatusRequest,
    PatchQuestionBankSetStatusResponse,
    QuestionBankCreateSetRequest,
    QuestionBankCreateSetResponse,
    QuestionBankDraftQueueItem,
    QuestionBankDraftQueueResponse,
    QuestionBankListResponse,
    QuestionBankSectionSummary,
    QuestionBankSetItem,
    ReadingBuilderQuestionOut,
    ReadingBuilderSaveRequest,
    ReadingBuilderSaveResponse,
    SpeakingBuilderQuestionIn,
    SpeakingBuilderQuestionOut,
    SpeakingBuilderSaveRequest,
    SpeakingBuilderSaveResponse,
    WritingBuilderSaveRequest,
    WritingBuilderSaveResponse,
)
from app.admin.writing_taxonomy import (
    assert_valid_exam_module,
    assert_valid_writing_question_type,
    assert_writing_task_exam_module_compatible,
    default_writing_question_type,
    writing_taxonomy_publish_blockers,
)
from app.mock_catalog.constants import MODULE_ORDER
from app.db.supabase_client import get_supabase
from app.practice.writing_track import normalize_set_exam_module

logger = logging.getLogger(__name__)

SKILLS = frozenset({"listening", "reading", "writing", "speaking"})
# New custom bank sets are one named unit (part 1). Legacy sets may still have more.
MAX_PARTS: dict[str, int] = {
    "listening": 1,
    "reading": 1,
    "writing": 1,
    "speaking": 1,
}
LEGACY_MAX_PARTS: dict[str, int] = {
    "listening": 4,
    "reading": 4,
    "writing": 2,
    "speaking": 3,
}
CUSTOM_BANK_NUMBER = 5
CUSTOM_BANK_TITLE = "Custom"


def _assert_skill(skill: str) -> str:
    s = skill.strip().lower()
    if s not in SKILLS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid skill.")
    return s


def _assert_part(module: str, part: int) -> None:
    max_p = LEGACY_MAX_PARTS.get(module, MAX_PARTS.get(module, 0))
    if part < 1 or part > max_p:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Part must be 1–{max_p} for {module}.",
        )


def _load_set_skill(sb: Any, set_id: str) -> tuple[dict[str, Any], str]:
    rows = (
        sb.table("practice_sets")
        .select(
            "id, set_number, title, difficulty, status, bank_id, exam_module, "
            "practice_banks(skill, bank_number, title)"
        )
        .eq("id", set_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Practice set not found.")
    row = rows[0]
    bank = row.get("practice_banks") or {}
    if isinstance(bank, list):
        bank = bank[0] if bank else {}
    skill = str(bank.get("skill") or "")
    if skill not in SKILLS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Practice set has invalid skill.")
    return row, skill


def _module_href(skill: str) -> dict[str, Any]:
    from app.practice.module_href import module_submit_config

    return module_submit_config(skill=skill, catalog_number=1, part=1)


def _bank_href(skill: str, hub_id: str) -> dict[str, Any]:
    return {
        "type": "bank",
        "module": skill,
        "href": f"/practice/{skill}/{hub_id}/exercise",
    }


def refresh_hub_submit_configs(*, practice_set_id: UUID, skill: str) -> None:
    """Wire hub submit_config for personalized practice.

    Custom (non–Phase0) hubs always use the bank exercise UI.
    Legacy Phase0 slugs keep mock module targeting when they still have content.
    """
    from app.practice.module_href import config_from_slug_or_defaults

    sb = get_supabase()
    sections = (
        sb.table("bank_sections")
        .select("id, part")
        .eq("practice_set_id", str(practice_set_id))
        .order("part")
        .execute()
    ).data or []
    total_q = 0
    first_part: int | None = None
    for sec in sections:
        if first_part is None and sec.get("part") is not None:
            first_part = int(sec["part"])
        count = (
            sb.table("bank_questions")
            .select("id", count="exact")
            .eq("section_id", str(sec["id"]))
            .limit(1)
            .execute()
        )
        total_q += int(count.count or 0)

    hubs = (
        sb.table("practice_hubs")
        .select("id, slug")
        .eq("set_id", str(practice_set_id))
        .execute()
    ).data or []
    for hub in hubs:
        hub_id = str(hub["id"])
        slug = str(hub.get("slug") or "")
        if slug.startswith("phase0-") and total_q > 0:
            config = config_from_slug_or_defaults(
                skill=skill,
                slug=slug,
                hub_id=hub_id,
                section_part=first_part,
            )
        else:
            config = _bank_href(skill, hub_id)
        sb.table("practice_hubs").update({"submit_config": config}).eq(
            "id", hub_id
        ).execute()


def _upsert_section(
    sb: Any,
    *,
    practice_set_id: str,
    module: str,
    part: int,
    fields: dict[str, Any],
) -> str:
    existing = (
        sb.table("bank_sections")
        .select("id")
        .eq("practice_set_id", practice_set_id)
        .eq("part", part)
        .limit(1)
        .execute()
    ).data or []
    payload = {
        **fields,
        "practice_set_id": practice_set_id,
        "module": module,
        "part": part,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if existing:
        section_id = str(existing[0]["id"])
        sb.table("bank_sections").update(payload).eq("id", section_id).execute()
        return section_id
    inserted = sb.table("bank_sections").insert(payload).execute().data or []
    if not inserted:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Could not create bank section.",
        )
    return str(inserted[0]["id"])


def _replace_questions(
    sb: Any,
    *,
    section_id: str,
    inserts: list[dict[str, Any]],
) -> None:
    sb.table("bank_questions").delete().eq("section_id", section_id).execute()
    if inserts:
        for row in inserts:
            row["section_id"] = section_id
        sb.table("bank_questions").insert(inserts).execute()


def list_question_bank(*, skill: str) -> QuestionBankListResponse:
    skill = _assert_skill(skill)
    sb = get_supabase()
    banks = (
        sb.table("practice_banks")
        .select("id, bank_number, title, skill")
        .eq("skill", skill)
        .order("bank_number")
        .execute()
    ).data or []
    if not banks:
        return QuestionBankListResponse(skill=skill, sets=[])

    bank_ids = [str(b["id"]) for b in banks]
    bank_by_id = {str(b["id"]): b for b in banks}
    sets = (
        sb.table("practice_sets")
        .select(
            "id, set_number, title, difficulty, bank_id, description, status, "
            "exam_module, created_at"
        )
        .in_("bank_id", bank_ids)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    set_ids = [str(s["id"]) for s in sets]
    hubs_by_set: dict[str, dict[str, Any]] = {}
    if set_ids:
        hubs = (
            sb.table("practice_hubs")
            .select("id, slug, set_id")
            .in_("set_id", set_ids)
            .execute()
        ).data or []
        for h in hubs:
            hubs_by_set[str(h["set_id"])] = h

    sections_by_set: dict[str, list[dict[str, Any]]] = {}
    if set_ids:
        sections = (
            sb.table("bank_sections")
            .select("id, practice_set_id, part")
            .in_("practice_set_id", set_ids)
            .execute()
        ).data or []
        section_ids = [str(s["id"]) for s in sections]
        q_counts: dict[str, int] = {sid: 0 for sid in section_ids}
        if section_ids:
            qs = (
                sb.table("bank_questions")
                .select("section_id")
                .in_("section_id", section_ids)
                .execute()
            ).data or []
            for q in qs:
                sid = str(q["section_id"])
                q_counts[sid] = q_counts.get(sid, 0) + 1
        for sec in sections:
            sid = str(sec["practice_set_id"])
            sections_by_set.setdefault(sid, []).append(
                {
                    **sec,
                    "question_count": q_counts.get(str(sec["id"]), 0),
                }
            )

    def _created_at_key(row: dict[str, Any]) -> datetime:
        raw = row.get("created_at")
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
        if raw:
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except ValueError:
                pass
        return datetime.min.replace(tzinfo=UTC)

    items: list[QuestionBankSetItem] = []
    # Newest first; keep bank/set ascending as tie-breaker
    sets_sorted = sorted(
        sets,
        key=lambda s: (
            -_created_at_key(s).timestamp(),
            int(bank_by_id.get(str(s["bank_id"]), {}).get("bank_number") or 0),
            int(s.get("set_number") or 0),
        ),
    )
    for s in sets_sorted:
        set_id = str(s["id"])
        bank = bank_by_id.get(str(s["bank_id"]), {})
        sec_rows = sections_by_set.get(set_id, [])
        by_part = {int(r["part"]): r for r in sec_rows}
        existing_max = max(by_part.keys()) if by_part else 0
        show_parts = max(MAX_PARTS[skill], existing_max, 1)
        section_summaries: list[QuestionBankSectionSummary] = []
        total_q = 0
        for p in range(1, show_parts + 1):
            row = by_part.get(p)
            count = int(row["question_count"]) if row else 0
            total_q += count
            section_summaries.append(
                QuestionBankSectionSummary(
                    part=p,
                    question_count=count,
                    has_content=count > 0,
                )
            )
        hub = hubs_by_set.get(set_id)
        bank_number = int(bank.get("bank_number") or 0)
        created = _created_at_key(s)
        items.append(
            QuestionBankSetItem(
                set_id=UUID(set_id),
                set_number=int(s["set_number"]),
                title=str(s["title"]),
                difficulty=str(s.get("difficulty") or "medium"),
                bank_id=UUID(str(s["bank_id"])),
                bank_number=bank_number,
                bank_title=str(bank.get("title") or ""),
                skill=skill,
                hub_id=UUID(str(hub["id"])) if hub else None,
                hub_slug=str(hub["slug"]) if hub else None,
                description=(str(s["description"]) if s.get("description") else None),
                status=str(s.get("status") or "draft"),
                is_custom=bank_number == CUSTOM_BANK_NUMBER,
                exam_module=normalize_set_exam_module(s.get("exam_module")),
                created_at=created if created.year > 1 else None,
                sections=section_summaries,
                total_questions=total_q,
            )
        )
    return QuestionBankListResponse(skill=skill, sets=items)


def list_question_bank_draft_queue() -> QuestionBankDraftQueueResponse:
    """Flat ordered list of draft practice sets across L/R/W/S for admin review."""
    sb = get_supabase()
    banks = (
        sb.table("practice_banks")
        .select("id, bank_number, title, skill")
        .execute()
    ).data or []
    bank_by_id = {str(b["id"]): b for b in banks}
    if not bank_by_id:
        return QuestionBankDraftQueueResponse(items=[], total=0)

    sets = (
        sb.table("practice_sets")
        .select("id, set_number, title, status, bank_id")
        .eq("status", "draft")
        .in_("bank_id", list(bank_by_id.keys()))
        .execute()
    ).data or []
    if not sets:
        return QuestionBankDraftQueueResponse(items=[], total=0)

    set_ids = [str(s["id"]) for s in sets]
    hubs_by_set: dict[str, dict[str, Any]] = {}
    hubs = (
        sb.table("practice_hubs")
        .select("id, set_id")
        .in_("set_id", set_ids)
        .execute()
    ).data or []
    for h in hubs:
        hubs_by_set[str(h["set_id"])] = h

    skill_rank = {name: idx for idx, name in enumerate(MODULE_ORDER)}
    draft_rows: list[tuple[tuple[int, int, int], QuestionBankDraftQueueItem]] = []
    for s in sets:
        bank = bank_by_id.get(str(s["bank_id"]))
        if not bank:
            continue
        skill = str(bank.get("skill") or "").lower()
        if skill not in SKILLS:
            continue
        set_id = str(s["id"])
        hub = hubs_by_set.get(set_id)
        item = QuestionBankDraftQueueItem(
            set_id=UUID(set_id),
            skill=skill,
            title=str(s.get("title") or ""),
            set_number=int(s.get("set_number") or 0),
            bank_number=int(bank.get("bank_number") or 0),
            status=str(s.get("status") or "draft"),
            hub_id=UUID(str(hub["id"])) if hub else None,
        )
        sort_key = (
            skill_rank.get(skill, 99),
            item.bank_number,
            item.set_number,
        )
        draft_rows.append((sort_key, item))

    draft_rows.sort(key=lambda row: row[0])
    items = [row[1] for row in draft_rows]
    return QuestionBankDraftQueueResponse(items=items, total=len(items))


def get_question_bank_set(*, set_id: UUID) -> QuestionBankSetItem:
    sb = get_supabase()
    row = (
        sb.table("practice_sets")
        .select(
            "id, set_number, title, difficulty, bank_id, description, status, "
            "exam_module, practice_banks(id, bank_number, title, skill)"
        )
        .eq("id", str(set_id))
        .limit(1)
        .execute()
    ).data
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Practice set not found.")
    s = row[0]
    bank = s.get("practice_banks") or {}
    if isinstance(bank, list):
        bank = bank[0] if bank else {}
    skill = _assert_skill(str(bank.get("skill") or ""))
    bank_number = int(bank.get("bank_number") or 0)
    hubs = (
        sb.table("practice_hubs")
        .select("id, slug")
        .eq("set_id", str(set_id))
        .limit(1)
        .execute()
    ).data or []
    hub = hubs[0] if hubs else None
    sections = (
        sb.table("bank_sections")
        .select("id, part")
        .eq("practice_set_id", str(set_id))
        .execute()
    ).data or []
    q_counts: dict[int, int] = {}
    for sec in sections:
        count = (
            sb.table("bank_questions")
            .select("id", count="exact")
            .eq("section_id", str(sec["id"]))
            .limit(1)
            .execute()
        )
        q_counts[int(sec["part"])] = int(count.count or 0)
    existing_max = max(q_counts.keys()) if q_counts else 0
    show_parts = max(MAX_PARTS[skill], existing_max, 1)
    section_summaries = [
        QuestionBankSectionSummary(
            part=p,
            question_count=q_counts.get(p, 0),
            has_content=q_counts.get(p, 0) > 0,
        )
        for p in range(1, show_parts + 1)
    ]
    return QuestionBankSetItem(
        set_id=UUID(str(s["id"])),
        set_number=int(s["set_number"]),
        title=str(s["title"]),
        difficulty=str(s.get("difficulty") or "medium"),
        bank_id=UUID(str(s["bank_id"])),
        bank_number=bank_number,
        bank_title=str(bank.get("title") or ""),
        skill=skill,
        hub_id=UUID(str(hub["id"])) if hub else None,
        hub_slug=str(hub["slug"]) if hub else None,
        description=(str(s["description"]) if s.get("description") else None),
        status=str(s.get("status") or "draft"),
        is_custom=bank_number == CUSTOM_BANK_NUMBER,
        exam_module=normalize_set_exam_module(s.get("exam_module")),
        sections=section_summaries,
        total_questions=sum(q_counts.values()),
    )


def _is_published_status(value: Any) -> bool:
    return str(value or "").strip().lower() == "published"


def _student_visible_status_change(prev: str, next_status: str) -> bool:
    """True when the assignable pool can change (enter or leave published)."""
    prev_s = str(prev or "").strip().lower()
    next_s = str(next_status or "").strip().lower()
    if prev_s == next_s:
        return False
    return _is_published_status(prev_s) or _is_published_status(next_s)


def _clear_practice_catalog_cache() -> None:
    try:
        from app.practice.catalog import clear_hub_catalog_cache

        clear_hub_catalog_cache()
    except Exception:
        pass
    try:
        from app.cache.hybrid_cache import invalidate_prefix

        invalidate_prefix("practice:section:")
    except Exception:
        pass


def _after_question_bank_mutation(
    *,
    student_visible: bool,
    bump_version: bool | None = None,
) -> None:
    """After a successful DB write: bump version if students can see it, always drop catalog caches.

    Status changes bump inside ``apply_practice_set_status`` (same transaction as
    the publish/unpublish write). Pass ``bump_version=False`` for that path so
    Python does not increment a second time. Content saves still bump here.
    Failures are retried, then raised — never swallowed.
    """
    do_bump = student_visible if bump_version is None else bump_version
    if do_bump:
        _bump_catalog_version_strict()
    _clear_practice_catalog_cache()


def _bump_catalog_version_strict(*, attempts: int = 3) -> int:
    from app.practice.repository import bump_practice_catalog_version

    last: BaseException | None = None
    for i in range(max(1, attempts)):
        try:
            return bump_practice_catalog_version()
        except Exception as exc:
            last = exc
            logger.exception("catalog version bump failed attempt=%s", i + 1)
    try:
        from app.reliability.metrics import record_event

        record_event("practice.catalog_version_bump_failed", detail="retries_exhausted")
    except Exception:
        pass
    assert last is not None
    raise last


def bank_publish_blockers(*, set_id: UUID | str, skill: str) -> list[str]:
    """Return human-readable blockers that prevent publishing a practice set."""
    skill = _assert_skill(skill)
    sb = get_supabase()
    sid = str(set_id)
    sections = (
        sb.table("bank_sections")
        .select("id, part, audio_key, passage_text, module")
        .eq("practice_set_id", sid)
        .order("part")
        .execute()
    ).data or []
    section_ids = [str(s["id"]) for s in sections if s.get("id")]
    questions: list[dict[str, Any]] = []
    if section_ids:
        questions = (
            sb.table("bank_questions")
            .select(
                "id, section_id, prompt, passage_text, audio_url, correct_answer, options"
            )
            .in_("section_id", section_ids)
            .execute()
        ).data or []

    qs_by_section: dict[str, list[dict[str, Any]]] = {}
    for q in questions:
        qs_by_section.setdefault(str(q.get("section_id") or ""), []).append(q)

    blockers: list[str] = []

    if skill == "listening":
        if not questions:
            blockers.append("Listening: add at least one question before publishing.")
            return blockers
        for sec in sections:
            sec_id = str(sec.get("id") or "")
            sec_qs = qs_by_section.get(sec_id) or []
            if not sec_qs:
                continue
            part = int(sec.get("part") or 0)
            audio = str(sec.get("audio_key") or "").strip()
            if not audio and not any(
                str(q.get("audio_url") or "").strip() for q in sec_qs
            ):
                blockers.append(f"Listening Part {part}: missing audio (R2 key).")
            for i, q in enumerate(sec_qs, start=1):
                if not str(q.get("correct_answer") or "").strip():
                    blockers.append(
                        f"Listening Part {part} Q{i}: missing correct answer."
                    )

    elif skill == "reading":
        if not questions:
            blockers.append("Reading: add at least one question before publishing.")
            return blockers
        has_passage = any(str(s.get("passage_text") or "").strip() for s in sections) or any(
            str(q.get("passage_text") or "").strip() for q in questions
        )
        if not has_passage:
            blockers.append("Reading: passage text is required.")
        for sec in sections:
            sec_id = str(sec.get("id") or "")
            sec_qs = qs_by_section.get(sec_id) or []
            part = int(sec.get("part") or 0)
            for i, q in enumerate(sec_qs, start=1):
                if not str(q.get("correct_answer") or "").strip():
                    blockers.append(
                        f"Reading Passage {part} Q{i}: missing correct answer."
                    )

    elif skill == "writing":
        set_rows = (
            sb.table("practice_sets")
            .select("exam_module")
            .eq("id", sid)
            .limit(1)
            .execute()
        ).data or []
        exam_module = set_rows[0].get("exam_module") if set_rows else None

        # Need question_type for taxonomy checks
        q_types: list[Any] = []
        if section_ids:
            typed = (
                sb.table("bank_questions")
                .select("question_type, prompt")
                .in_("section_id", section_ids)
                .execute()
            ).data or []
            q_types = [q.get("question_type") for q in typed]
            # Prefer typed query prompts when available
            has_prompt = any(str(s.get("passage_text") or "").strip() for s in sections) or any(
                str(q.get("prompt") or "").strip() for q in typed
            )
        else:
            has_prompt = any(str(s.get("passage_text") or "").strip() for s in sections) or any(
                str(q.get("prompt") or "").strip() for q in questions
            )

        if not has_prompt:
            blockers.append("Writing: task prompt is required.")
        blockers.extend(
            writing_taxonomy_publish_blockers(
                exam_module=exam_module,
                question_types=q_types,
                has_prompt=has_prompt,
            )
        )

    elif skill == "speaking":
        ready = [
            q
            for q in questions
            if str(q.get("prompt") or "").strip()
            or str(
                (q.get("options") or {}).get("video_url")
                if isinstance(q.get("options"), dict)
                else ""
            ).strip()
        ]
        if not ready:
            blockers.append(
                "Speaking: add at least one question with a prompt or video before publishing."
            )

    return blockers


def patch_question_bank_set_status(
    *,
    set_id: UUID,
    body: PatchQuestionBankSetStatusRequest,
    admin_id: UUID,
) -> PatchQuestionBankSetStatusResponse:
    sb = get_supabase()
    set_row, skill = _load_set_skill(sb, str(set_id))
    next_status = body.status
    prev = str(set_row.get("status") or "draft")

    if next_status == "published":
        blockers = bank_publish_blockers(set_id=set_id, skill=skill)
        if blockers:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Cannot publish incomplete practice set.",
                    "code": "publish_blocked",
                    "blockers": blockers,
                },
            )

    used_db_bump = True
    try:
        applied = sb.rpc(
            "apply_practice_set_status",
            {"p_set_id": str(set_id), "p_status": next_status},
        ).execute()
        payload = applied.data
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        job_id = payload.get("job_id") if isinstance(payload, dict) else None
    except APIError as exc:
        msg = str(exc).lower()
        # Backward-compatible fallback for environments missing catalog bump SQL function.
        if "bump_practice_catalog_version" not in msg:
            raise
        used_db_bump = False
        job_id = None
        sb.table("practice_sets").update({"status": next_status}).eq("id", str(set_id)).execute()

    refresh_hub_submit_configs(practice_set_id=set_id, skill=skill)
    _after_question_bank_mutation(
        student_visible=_student_visible_status_change(prev, next_status),
        bump_version=False if used_db_bump else None,
    )
    if job_id:
        logger.info(
            "practice.catalog_changed enqueued set=%s skill=%s job_id=%s",
            set_id,
            skill,
            job_id,
        )

    log_admin_action(
        admin_id=admin_id,
        action="question_bank.set_status",
        resource_type="practice_set",
        resource_id=set_id,
        metadata={
            "skill": skill,
            "from": prev,
            "to": next_status,
        },
    )
    return PatchQuestionBankSetStatusResponse(
        set_id=set_id,
        skill=skill,
        status=next_status,
        ok=True,
    )


def create_question_bank_set(
    *,
    body: QuestionBankCreateSetRequest,
    admin_id: UUID,
) -> QuestionBankCreateSetResponse:
    skill = _assert_skill(body.skill)
    title = body.title.strip()
    if not title:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "title is required.")
    description = (body.description or "").strip() or None
    status_val = body.status
    difficulty = body.difficulty

    # Writing requires an explicit exam_module (no silent academic default).
    exam_module: str | None = None
    if skill == "writing":
        exam_module = assert_valid_exam_module(body.exam_module, required=True)
    elif body.exam_module is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "exam_module is only allowed on Writing practice sets.",
                "code": "exam_module_skill_mismatch",
            },
        )

    # New sets have no content yet — force draft; publish via PATCH after fill.
    if status_val == "published":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Create sets as draft, add content, then publish.",
        )

    sb = get_supabase()
    banks = (
        sb.table("practice_banks")
        .select("id")
        .eq("skill", skill)
        .eq("bank_number", CUSTOM_BANK_NUMBER)
        .limit(1)
        .execute()
    ).data or []
    if banks:
        bank_id = str(banks[0]["id"])
    else:
        created_bank = (
            sb.table("practice_banks")
            .insert(
                {
                    "skill": skill,
                    "bank_number": CUSTOM_BANK_NUMBER,
                    "title": CUSTOM_BANK_TITLE,
                    "weakness_tags": [],
                }
            )
            .execute()
        ).data
        if not created_bank:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Could not create custom practice bank.",
            )
        bank_id = str(created_bank[0]["id"])

    existing = (
        sb.table("practice_sets")
        .select("set_number")
        .eq("bank_id", bank_id)
        .order("set_number", desc=True)
        .limit(1)
        .execute()
    ).data or []
    next_set = int(existing[0]["set_number"]) + 1 if existing else 1

    insert_row: dict[str, Any] = {
        "bank_id": bank_id,
        "set_number": next_set,
        "title": title,
        "difficulty": difficulty,
        "description": description,
        "status": status_val,
        "created_by": str(admin_id),
    }
    if exam_module is not None:
        insert_row["exam_module"] = exam_module

    set_rows = (
        sb.table("practice_sets")
        .insert(insert_row)
        .execute()
    ).data
    if not set_rows:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Could not create practice set.",
        )
    set_id = str(set_rows[0]["id"])

    sort_rows = (
        sb.table("practice_hubs")
        .select("sort_order")
        .order("sort_order", desc=True)
        .limit(1)
        .execute()
    ).data or []
    next_sort = int(sort_rows[0]["sort_order"] or 0) + 1 if sort_rows else 1
    slug = f"{skill}-custom-{uuid4().hex[:8]}"
    hub_videos = videos_for_skill(skill)
    hub_rows = (
        sb.table("practice_hubs")
        .insert(
            {
                "set_id": set_id,
                "slug": slug,
                "videos": hub_videos,
                "practice_prompt": "",
                "submit_config": {},
                "estimated_min": 25,
                "sort_order": next_sort,
            }
        )
        .execute()
    ).data
    if not hub_rows:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Could not create practice hub for set.",
        )
    hub_id = str(hub_rows[0]["id"])
    sb.table("practice_hubs").update(
        {"submit_config": _bank_href(skill, hub_id)}
    ).eq("id", hub_id).execute()

    log_admin_action(
        admin_id=admin_id,
        action="question_bank.set_create",
        resource_type="practice_set",
        resource_id=UUID(set_id),
        metadata={
            "skill": skill,
            "title": title,
            "difficulty": difficulty,
            "bank_number": CUSTOM_BANK_NUMBER,
            "set_number": next_set,
            "hub_id": hub_id,
            "exam_module": exam_module,
        },
    )
    return QuestionBankCreateSetResponse(
        set_id=UUID(set_id),
        skill=skill,
        title=title,
        hub_id=UUID(hub_id),
        parts=MAX_PARTS[skill],
        bank_number=CUSTOM_BANK_NUMBER,
        set_number=next_set,
        status=status_val,
        exam_module=exam_module,  # type: ignore[arg-type]
    )


def patch_question_bank_set(
    *,
    set_id: UUID,
    body: PatchQuestionBankSetRequest,
    admin_id: UUID,
) -> PatchQuestionBankSetResponse:
    """Update Writing set metadata (exam_module)."""
    sb = get_supabase()
    set_row, skill = _load_set_skill(sb, str(set_id))

    if body.exam_module is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "exam_module is required on this update.",
                "code": "exam_module_required",
            },
        )

    if skill != "writing":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "exam_module is only allowed on Writing practice sets.",
                "code": "exam_module_skill_mismatch",
            },
        )

    exam_module = assert_valid_exam_module(body.exam_module, required=True)

    # Reject taxonomy mismatches against existing questions.
    sections = (
        sb.table("bank_sections")
        .select("id")
        .eq("practice_set_id", str(set_id))
        .execute()
    ).data or []
    section_ids = [str(s["id"]) for s in sections if s.get("id")]
    if section_ids:
        qs = (
            sb.table("bank_questions")
            .select("question_type")
            .in_("section_id", section_ids)
            .execute()
        ).data or []
        for q in qs:
            q_type = q.get("question_type")
            if not q_type:
                continue
            assert_writing_task_exam_module_compatible(
                question_type=q_type,
                exam_module=exam_module,
            )

    sb.table("practice_sets").update({"exam_module": exam_module}).eq(
        "id", str(set_id)
    ).execute()

    _after_question_bank_mutation(
        student_visible=_is_published_status(set_row.get("status"))
    )
    log_admin_action(
        admin_id=admin_id,
        action="question_bank.set_patch",
        resource_type="practice_set",
        resource_id=set_id,
        metadata={"skill": skill, "exam_module": exam_module},
    )
    return PatchQuestionBankSetResponse(
        set_id=set_id,
        skill=skill,
        exam_module=exam_module,  # type: ignore[arg-type]
        ok=True,
    )


def delete_question_bank_set(
    *,
    set_id: UUID,
    admin_id: UUID,
) -> dict[str, Any]:
    """Delete a custom (bank 5) practice set. Seeded catalogue sets are protected."""
    sb = get_supabase()
    set_row, skill = _load_set_skill(sb, str(set_id))
    bank = set_row.get("practice_banks") or {}
    if isinstance(bank, list):
        bank = bank[0] if bank else {}
    bank_number = int(bank.get("bank_number") or 0)
    if bank_number != CUSTOM_BANK_NUMBER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only custom practice sets can be deleted. Archive seeded catalogue sets instead.",
        )

    title = str(set_row.get("title") or "")
    set_number = int(set_row.get("set_number") or 0)
    was_published = _is_published_status(set_row.get("status"))
    sid = str(set_id)
    # Ledger FKs are ON DELETE RESTRICT so assignments must be removed first.
    sb.table("user_practice_assignments").delete().eq("practice_set_id", sid).execute()
    try:
        sb.table("practice_sets").delete().eq("id", sid).execute()
    except APIError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "Cannot delete this practice set because it is still referenced.",
                "code": "delete_blocked",
                "detail": getattr(exc, "message", None) or str(exc),
            },
        ) from exc

    _after_question_bank_mutation(student_visible=was_published)

    log_admin_action(
        admin_id=admin_id,
        action="question_bank.set_delete",
        resource_type="practice_set",
        resource_id=set_id,
        metadata={
            "skill": skill,
            "title": title,
            "bank_number": bank_number,
            "set_number": set_number,
        },
    )
    return {"ok": True, "deleted_id": set_id}


def _is_choose_two(q_type_ui: str, correct: str, options: list | None) -> bool:
    if q_type_ui == MCQ_CHOOSE_TWO_UI:
        return True
    if listening_to_slug(q_type_ui) != "mcq":
        return False
    parts = [p.strip() for p in (correct or "").split(",") if p.strip()]
    return len(parts) >= 2


def save_bank_listening(
    *,
    set_id: UUID,
    part: int,
    body: ListeningBuilderSaveRequest,
    admin_id: UUID,
) -> ListeningBuilderSaveResponse:
    sb = get_supabase()
    set_row, skill = _load_set_skill(sb, str(set_id))
    if skill != "listening":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set is not a listening set.")
    _assert_part("listening", part)
    audio_key = body.audio_key.strip()
    if not audio_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "audio_key is required.")

    section_id = _upsert_section(
        sb,
        practice_set_id=str(set_id),
        module="listening",
        part=part,
        fields={
            "audio_key": audio_key,
            "instructions": (body.instructions or "").strip() or None,
            "title": f"Listening Part {part}",
        },
    )
    inserts: list[dict[str, Any]] = []
    qnum = 1
    for q in body.questions:
        slug = listening_to_slug(q.question_type)
        choose_two = bool(q.choose_two) or q.question_type == MCQ_CHOOSE_TWO_UI
        passage: str | None = None
        if qnum == 1 and body.instructions and body.instructions.strip():
            passage = body.instructions.strip()
        elif q.instructions and q.instructions.strip():
            passage = q.instructions.strip()
        base: dict[str, Any] = {
            "question_type": slug,
            "prompt": q.prompt,
            "passage_text": passage,
            "options": q.options,
            "skill_tag": q.skill_tag or slug,
            "audio_url": audio_key,
            "difficulty": q.difficulty if q.difficulty in ("easy", "medium", "hard") else "medium",
        }
        if choose_two and slug == "mcq":
            rows = expand_choose_two_rows(
                base=base,
                correct_answer=q.correct_answer,
                alt_answers=q.alt_answers,
            )
        else:
            rows = [
                {
                    **base,
                    "correct_answer": join_answers(q.correct_answer, q.alt_answers),
                }
            ]
        for row in rows:
            row["question_number"] = qnum
            inserts.append(row)
            qnum += 1
    _replace_questions(sb, section_id=section_id, inserts=inserts)
    refresh_hub_submit_configs(practice_set_id=set_id, skill=skill)
    _after_question_bank_mutation(
        student_visible=_is_published_status(set_row.get("status"))
    )
    log_admin_action(
        admin_id=admin_id,
        action="question_bank.listening_save",
        resource_type="practice_set",
        resource_id=set_id,
        metadata={"part": part, "question_count": len(inserts)},
    )
    return ListeningBuilderSaveResponse(
        ok=True,
        questions_written=len(inserts),
        part=part,
        audio_key=audio_key,
    )


def load_bank_listening(*, set_id: UUID, part: int) -> BankListeningPartResponse:
    sb = get_supabase()
    _, skill = _load_set_skill(sb, str(set_id))
    if skill != "listening":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set is not a listening set.")
    _assert_part("listening", part)
    section = (
        sb.table("bank_sections")
        .select("id, audio_key, instructions")
        .eq("practice_set_id", str(set_id))
        .eq("part", part)
        .limit(1)
        .execute()
    ).data or []
    if not section:
        return BankListeningPartResponse(practice_set_id=set_id, part=part)
    sec = section[0]
    rows = (
        sb.table("bank_questions")
        .select(
            "id, question_number, question_type, prompt, passage_text, "
            "options, correct_answer, skill_tag, audio_url, difficulty"
        )
        .eq("section_id", str(sec["id"]))
        .order("question_number")
        .execute()
    ).data or []
    audio_key = sec.get("audio_key") or (rows[0].get("audio_url") if rows else None)
    instructions = sec.get("instructions")
    questions: list[ListeningBuilderQuestionOut] = []
    i = 0
    while i < len(rows):
        row = rows[i]
        if instructions is None and row.get("passage_text"):
            instructions = str(row["passage_text"])
        primary, alts = split_answers(row.get("correct_answer"))
        slug = str(row["question_type"])
        if slug.lower() in ("multiple_choice", "multiple-choice"):
            slug = "mcq"
        choose_two = _is_choose_two(slug, primary, row.get("options"))
        if slug == "mcq" and "," in primary:
            choose_two = True
        if i + 1 < len(rows) and looks_like_choose_two_pair(row, rows[i + 1]):
            letters = [
                str(row.get("correct_answer") or "").strip().upper(),
                str(rows[i + 1].get("correct_answer") or "").strip().upper(),
            ]
            choose_two = True
            primary = ",".join(letters)
            alts = []
            i += 1
        questions.append(
            ListeningBuilderQuestionOut(
                id=UUID(str(row["id"])),
                question_number=int(row["question_number"]),
                question_type=listening_to_display(slug, choose_two=choose_two),
                prompt=str(row.get("prompt") or ""),
                instructions=row.get("passage_text"),
                options=row.get("options"),
                correct_answer=primary,
                alt_answers=alts,
                skill_tag=row.get("skill_tag"),
                choose_two=choose_two,
                difficulty=(
                    row.get("difficulty")
                    if row.get("difficulty") in ("easy", "medium", "hard")
                    else "medium"
                ),
            )
        )
        i += 1
    return BankListeningPartResponse(
        practice_set_id=set_id,
        part=part,
        audio_key=str(audio_key) if audio_key else None,
        instructions=str(instructions) if instructions else None,
        questions=questions,
    )


def save_bank_reading(
    *,
    set_id: UUID,
    part: int,
    body: ReadingBuilderSaveRequest,
    admin_id: UUID,
) -> ReadingBuilderSaveResponse:
    sb = get_supabase()
    set_row, skill = _load_set_skill(sb, str(set_id))
    if skill != "reading":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set is not a reading set.")
    _assert_part("reading", part)
    passage = (body.passage_text or "").strip()
    section_id = _upsert_section(
        sb,
        practice_set_id=str(set_id),
        module="reading",
        part=part,
        fields={
            "passage_text": passage or None,
            "title": f"Reading Passage {part}",
        },
    )
    inserts: list[dict[str, Any]] = []
    qnum = 1
    for q in body.questions:
        slug = to_slug(q.question_type)
        letters = parse_choose_two_letters(q.correct_answer)
        base: dict[str, Any] = {
            "question_type": slug,
            "prompt": q.prompt,
            "passage_text": passage or None,
            "options": q.options,
            "skill_tag": q.skill_tag or slug,
            "difficulty": q.difficulty if q.difficulty in ("easy", "medium", "hard") else "medium",
        }
        if slug == "mcq" and len(letters) >= 2:
            rows = expand_choose_two_rows(
                base=base,
                correct_answer=q.correct_answer,
                alt_answers=q.alt_answers,
            )
        else:
            rows = [
                {
                    **base,
                    "correct_answer": join_answers(q.correct_answer, q.alt_answers),
                }
            ]
        for row in rows:
            row["question_number"] = qnum
            inserts.append(row)
            qnum += 1
    _replace_questions(sb, section_id=section_id, inserts=inserts)
    refresh_hub_submit_configs(practice_set_id=set_id, skill=skill)
    _after_question_bank_mutation(
        student_visible=_is_published_status(set_row.get("status"))
    )
    log_admin_action(
        admin_id=admin_id,
        action="question_bank.reading_save",
        resource_type="practice_set",
        resource_id=set_id,
        metadata={"part": part, "question_count": len(inserts)},
    )
    return ReadingBuilderSaveResponse(
        ok=True, questions_written=len(inserts), part=part
    )


def load_bank_reading(*, set_id: UUID, part: int) -> BankReadingPartResponse:
    sb = get_supabase()
    _, skill = _load_set_skill(sb, str(set_id))
    if skill != "reading":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set is not a reading set.")
    _assert_part("reading", part)
    section = (
        sb.table("bank_sections")
        .select("id, passage_text")
        .eq("practice_set_id", str(set_id))
        .eq("part", part)
        .limit(1)
        .execute()
    ).data or []
    if not section:
        return BankReadingPartResponse(practice_set_id=set_id, part=part)
    sec = section[0]
    rows = (
        sb.table("bank_questions")
        .select(
            "id, question_number, question_type, prompt, options, "
            "correct_answer, skill_tag, passage_text, difficulty"
        )
        .eq("section_id", str(sec["id"]))
        .order("question_number")
        .execute()
    ).data or []
    from app.admin.question_types import to_display

    questions: list[ReadingBuilderQuestionOut] = []
    for row in rows:
        primary, alts = split_answers(row.get("correct_answer"))
        questions.append(
            ReadingBuilderQuestionOut(
                id=UUID(str(row["id"])),
                question_number=int(row["question_number"]),
                question_type=to_display(str(row["question_type"])),
                prompt=str(row.get("prompt") or ""),
                options=row.get("options"),
                correct_answer=primary,
                alt_answers=alts,
                skill_tag=row.get("skill_tag"),
                difficulty=(
                    row.get("difficulty")
                    if row.get("difficulty") in ("easy", "medium", "hard")
                    else "medium"
                ),
            )
        )
    passage = str(sec.get("passage_text") or "")
    if not passage and rows:
        passage = str(rows[0].get("passage_text") or "")
    return BankReadingPartResponse(
        practice_set_id=set_id,
        part=part,
        passage_text=passage,
        questions=questions,
    )


def save_bank_writing(
    *,
    set_id: UUID,
    part: int,
    body: WritingBuilderSaveRequest,
    admin_id: UUID,
) -> WritingBuilderSaveResponse:
    sb = get_supabase()
    set_row, skill = _load_set_skill(sb, str(set_id))
    if skill != "writing":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set is not a writing set.")
    _assert_part("writing", part)
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "prompt is required.")
    q_type = assert_valid_writing_question_type(body.question_type, part=part)

    exam_module = normalize_set_exam_module(set_row.get("exam_module"))
    if body.exam_module is not None:
        exam_module = assert_valid_exam_module(body.exam_module, required=True)
        sb.table("practice_sets").update({"exam_module": exam_module}).eq(
            "id", str(set_id)
        ).execute()

    if exam_module is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "message": (
                    "Set exam_module must be set before saving Writing content "
                    "(academic, general_training, or both)."
                ),
                "code": "exam_module_required",
            },
        )
    assert_writing_task_exam_module_compatible(
        question_type=q_type,
        exam_module=exam_module,
    )

    # task1_general is a letter — chart/image is optional (same as academic).
    image_url = (body.image_url or "").strip() or None
    if q_type == "task1_general":
        # Do not require a chart payload; clear empty keys only.
        image_url = image_url or None
    options = dict(body.options or {})
    if image_url is not None:
        options["image_url"] = image_url
    elif q_type == "task1_general":
        options.pop("image_url", None)
        options.pop("chart", None)
    if "min_words" not in options:
        options["min_words"] = 150 if part == 1 else 250

    section_id = _upsert_section(
        sb,
        practice_set_id=str(set_id),
        module="writing",
        part=part,
        fields={
            "title": f"Writing Task {part}",
            "image_url": image_url,
            "passage_text": prompt,
        },
    )
    inserts = [
        {
            "question_number": 1,
            "question_type": q_type,
            "prompt": prompt,
            "options": options,
            "correct_answer": None,
            "skill_tag": "writing",
        }
    ]
    _replace_questions(sb, section_id=section_id, inserts=inserts)
    refresh_hub_submit_configs(practice_set_id=set_id, skill=skill)
    _after_question_bank_mutation(
        student_visible=_is_published_status(set_row.get("status"))
    )
    log_admin_action(
        admin_id=admin_id,
        action="question_bank.writing_save",
        resource_type="practice_set",
        resource_id=set_id,
        metadata={"part": part, "question_type": q_type, "exam_module": exam_module},
    )
    return WritingBuilderSaveResponse(
        ok=True, part=part, question_type=q_type, image_url=image_url
    )


def load_bank_writing(*, set_id: UUID, part: int) -> BankWritingPartResponse:
    sb = get_supabase()
    _, skill = _load_set_skill(sb, str(set_id))
    if skill != "writing":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set is not a writing set.")
    _assert_part("writing", part)
    section = (
        sb.table("bank_sections")
        .select("id, image_url, passage_text")
        .eq("practice_set_id", str(set_id))
        .eq("part", part)
        .limit(1)
        .execute()
    ).data or []
    if not section:
        return BankWritingPartResponse(
            practice_set_id=set_id,
            part=part,
            question_type=default_writing_question_type(part),
        )
    sec = section[0]
    rows = (
        sb.table("bank_questions")
        .select("id, question_type, prompt, options")
        .eq("section_id", str(sec["id"]))
        .order("question_number")
        .limit(1)
        .execute()
    ).data or []
    opts: dict[str, Any] = {}
    prompt = str(sec.get("passage_text") or "")
    q_type = default_writing_question_type(part)
    qid = None
    if rows:
        row = rows[0]
        qid = UUID(str(row["id"]))
        prompt = str(row.get("prompt") or prompt)
        q_type = str(row.get("question_type") or q_type)
        if isinstance(row.get("options"), dict):
            opts = dict(row["options"])
    image_url = sec.get("image_url") or opts.get("image_url")
    preview = None
    if image_url:
        try:
            from app.storage.r2 import generate_signed_url

            preview = generate_signed_url(str(image_url))
        except Exception:
            preview = None
    return BankWritingPartResponse(
        practice_set_id=set_id,
        part=part,
        question_id=qid,
        question_type=q_type,
        prompt=prompt,
        options=opts,
        image_url=str(image_url) if image_url else None,
        image_preview_url=preview,
    )


def _speaking_options(part: int, q: SpeakingBuilderQuestionIn) -> dict[str, Any]:
    speak = int(q.speak_time_sec) if q.speak_time_sec is not None else 15
    min_skip = int(q.min_skip_sec) if q.min_skip_sec is not None else 5
    if min_skip > speak:
        min_skip = speak
    prep = int(q.prep_sec) if q.prep_sec is not None else (60 if part == 2 else 0)
    record = (
        int(q.record_sec)
        if q.record_sec is not None
        else (120 if part == 2 else 45 if part == 1 else 60)
    )
    video_key = (q.video_url or "").strip() or None
    return {
        "kind": "part2_intro" if part == 2 else "question",
        "part_label": f"Part {part}",
        "speak_time_sec": max(1, speak),
        "min_skip_sec": max(0, min_skip),
        "prep_sec": max(0, prep),
        "record_sec": max(1, record),
        "video_url": video_key,
    }


def save_bank_speaking(
    *,
    set_id: UUID,
    part: int,
    body: SpeakingBuilderSaveRequest,
    admin_id: UUID,
) -> SpeakingBuilderSaveResponse:
    sb = get_supabase()
    set_row, skill = _load_set_skill(sb, str(set_id))
    if skill != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set is not a speaking set.")
    _assert_part("speaking", part)
    for q in body.questions:
        if part == 2 and not (q.video_url or "").strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Part 2 requires a short examiner video (upload 10–15s clip).",
            )
    section_id = _upsert_section(
        sb,
        practice_set_id=str(set_id),
        module="speaking",
        part=part,
        fields={"title": f"Speaking Part {part}"},
    )
    inserts: list[dict[str, Any]] = []
    for i, q in enumerate(body.questions, start=1):
        inserts.append(
            {
                "question_number": i,
                "question_type": f"speaking_part{part}",
                "prompt": q.prompt.strip(),
                "options": _speaking_options(part, q),
                "skill_tag": "speaking",
            }
        )
    _replace_questions(sb, section_id=section_id, inserts=inserts)
    refresh_hub_submit_configs(practice_set_id=set_id, skill=skill)
    _after_question_bank_mutation(
        student_visible=_is_published_status(set_row.get("status"))
    )
    log_admin_action(
        admin_id=admin_id,
        action="question_bank.speaking_save",
        resource_type="practice_set",
        resource_id=set_id,
        metadata={"part": part, "question_count": len(inserts)},
    )
    return SpeakingBuilderSaveResponse(ok=True, part=part, questions_written=len(inserts))


def load_bank_speaking(*, set_id: UUID, part: int) -> BankSpeakingPartResponse:
    sb = get_supabase()
    _, skill = _load_set_skill(sb, str(set_id))
    if skill != "speaking":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set is not a speaking set.")
    _assert_part("speaking", part)
    section = (
        sb.table("bank_sections")
        .select("id")
        .eq("practice_set_id", str(set_id))
        .eq("part", part)
        .limit(1)
        .execute()
    ).data or []
    if not section:
        return BankSpeakingPartResponse(practice_set_id=set_id, part=part)
    rows = (
        sb.table("bank_questions")
        .select("id, question_number, prompt, options")
        .eq("section_id", str(section[0]["id"]))
        .order("question_number")
        .execute()
    ).data or []
    questions: list[SpeakingBuilderQuestionOut] = []
    for row in rows:
        opts = row.get("options") if isinstance(row.get("options"), dict) else {}
        video = opts.get("video_url")
        preview = None
        if video:
            try:
                from app.storage.r2 import generate_signed_url

                preview = generate_signed_url(str(video))
            except Exception:
                preview = None
        questions.append(
            SpeakingBuilderQuestionOut(
                id=UUID(str(row["id"])),
                question_number=int(row["question_number"]),
                prompt=str(row.get("prompt") or ""),
                speak_time_sec=int(opts.get("speak_time_sec") or 15),
                min_skip_sec=int(opts.get("min_skip_sec") or 5),
                prep_sec=int(opts.get("prep_sec") or 0),
                record_sec=int(opts.get("record_sec") or 45),
                video_url=str(video) if video else None,
                video_preview_url=preview,
            )
        )
    return BankSpeakingPartResponse(
        practice_set_id=set_id, part=part, questions=questions
    )


def default_bank_audio_key(*, set_id: UUID, part: int) -> str:
    return f"bank/{set_id}/listening/part{part}/audio.mp3"


def default_bank_watch_video_key(*, set_id: UUID, ext: str = "mp4") -> str:
    safe = (ext or "mp4").strip().lower().lstrip(".")
    if safe not in {"mp4", "webm", "mov"}:
        safe = "mp4"
    return f"bank/{set_id}/watch/intro.{safe}"


def _missing_intro_column(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "intro_video_key" in msg or "intro_stream_uid" in msg


def _intro_column_unavailable(exc: APIError) -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "practice_sets is missing intro_stream_uid / intro_video_key. "
            "Apply backend/supabase/migrations/20260811170000_practice_sets_intro_video_key.sql."
        ),
    )


def get_set_intro_video_key(*, set_id: UUID) -> str | None:
    sb = get_supabase()
    try:
        rows = (
            sb.table("practice_sets")
            .select("intro_video_key")
            .eq("id", str(set_id))
            .limit(1)
            .execute()
        ).data or []
    except APIError as exc:
        if _missing_intro_column(exc):
            return None
        raise
    if not rows:
        return None
    key = str(rows[0].get("intro_video_key") or "").strip()
    return key or None


def get_set_intro_stream_uid(*, set_id: UUID) -> str | None:
    sb = get_supabase()
    try:
        rows = (
            sb.table("practice_sets")
            .select("intro_stream_uid")
            .eq("id", str(set_id))
            .limit(1)
            .execute()
        ).data or []
    except APIError as exc:
        if _missing_intro_column(exc):
            return None
        raise
    if not rows:
        return None
    uid = str(rows[0].get("intro_stream_uid") or "").strip()
    return uid or None


def _after_intro_update(*, status: Any = None) -> None:
    _after_question_bank_mutation(student_visible=_is_published_status(status))
    try:
        from app.cache.hybrid_cache import invalidate_prefix

        invalidate_prefix("practice:hub:detail:")
    except Exception:
        pass


def set_intro_stream_uid(*, set_id: UUID, stream_uid: str) -> str:
    sb = get_supabase()
    value = (stream_uid or "").strip()
    if not value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="stream_uid required")
    try:
        updated = (
            sb.table("practice_sets")
            .update({"intro_stream_uid": value})
            .eq("id", str(set_id))
            .execute()
        ).data
    except APIError as exc:
        if _missing_intro_column(exc):
            raise _intro_column_unavailable(exc) from exc
        raise
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Practice set not found.")
    try:
        row = updated[0] if isinstance(updated, list) else updated
        _after_intro_update(status=(row or {}).get("status") if isinstance(row, dict) else None)
    except Exception:
        pass
    return value


def set_intro_video_key(*, set_id: UUID, key: str) -> str:
    sb = get_supabase()
    value = (key or "").strip()
    if not value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="video key required")
    try:
        updated = (
            sb.table("practice_sets")
            .update({"intro_video_key": value})
            .eq("id", str(set_id))
            .execute()
        ).data
    except APIError as exc:
        if _missing_intro_column(exc):
            raise _intro_column_unavailable(exc) from exc
        raise
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Practice set not found.")
    try:
        row = updated[0] if isinstance(updated, list) else updated
        _after_intro_update(status=(row or {}).get("status") if isinstance(row, dict) else None)
    except Exception:
        pass
    return value


def default_bank_writing_image_key(*, set_id: UUID, part: int) -> str:
    return f"bank/{set_id}/writing/part{part}/image"
