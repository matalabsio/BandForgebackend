"""Business logic for practice hubs and mock unlock."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.practice import repository
from app.practice.schemas import (
    HubCompleteOut,
    MockUnlockOut,
    PracticeHubDetailOut,
    PracticeHubOut,
    PracticeProgressOut,
    PracticeVideo,
    SkillHubProgressOut,
)

SKILLS = repository.SKILLS

LOCKED_HUB_MESSAGE = "Complete the previous practice set to unlock this one."


def _effective_required(*, catalog_total: int, configured: int) -> int:
    if catalog_total <= 0:
        return configured
    if catalog_total < configured:
        return catalog_total
    return configured


def _hub_status(progress_map: dict[str, dict[str, Any]], hub_id: str) -> str:
    return str(progress_map.get(hub_id, {}).get("status") or "pending")


def accessible_hub_ids_for_skill(
    *,
    user_id: UUID,
    skill: str,
    progress_map: dict[str, dict[str, Any]] | None = None,
    hub_rows: list[dict[str, Any]] | None = None,
) -> set[str]:
    """Completed hubs stay open; only the next incomplete hub in sort_order is unlocked."""
    progress = progress_map if progress_map is not None else repository.get_user_progress_map(user_id)
    rows = hub_rows if hub_rows is not None else repository.list_hubs_for_skill(skill)
    accessible: set[str] = set()
    unlocked_next = True
    for row in rows:
        flat = repository._flatten_hub_row(row)
        hub_id = str(flat["id"])
        status = _hub_status(progress, hub_id)
        if status == "completed":
            accessible.add(hub_id)
            continue
        if unlocked_next:
            accessible.add(hub_id)
            unlocked_next = False
    return accessible


def assert_hub_accessible(*, user_id: UUID, hub_id: str) -> dict[str, Any]:
    """Raise 403 if this hub is locked behind an incomplete earlier set. Returns flat hub row."""
    row = repository.get_hub_by_id(hub_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Hub not found")
    flat = repository._flatten_hub_row(row)
    skill = flat.get("skill")
    if skill not in SKILLS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Hub not found")
    allowed = accessible_hub_ids_for_skill(user_id=user_id, skill=str(skill))
    if str(hub_id) not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "message": LOCKED_HUB_MESSAGE,
                "code": "hub_locked",
                "skill": skill,
                "hub_id": str(hub_id),
            },
        )
    return flat


def current_hub_id_for_skill(
    *,
    user_id: UUID,
    skill: str,
    progress_map: dict[str, dict[str, Any]] | None = None,
    hub_rows: list[dict[str, Any]] | None = None,
) -> str | None:
    """First accessible incomplete hub for the skill; if all done, last completed for review."""
    if skill not in SKILLS:
        return None
    progress = progress_map if progress_map is not None else repository.get_user_progress_map(user_id)
    rows = hub_rows if hub_rows is not None else repository.list_hubs_for_skill(skill)
    if not rows:
        return None
    allowed = accessible_hub_ids_for_skill(
        user_id=user_id,
        skill=skill,
        progress_map=progress,
        hub_rows=rows,
    )
    last_completed: str | None = None
    for row in rows:
        flat = repository._flatten_hub_row(row)
        hub_id = str(flat["id"])
        if hub_id not in allowed:
            continue
        status = _hub_status(progress, hub_id)
        if status == "completed":
            last_completed = hub_id
            continue
        return hub_id
    return last_completed


def skill_progress(
    *,
    user_id: UUID,
    skill: str,
    progress_map: dict[str, dict[str, Any]] | None = None,
    hub_rows: list[dict[str, Any]] | None = None,
    mock_row: dict[str, Any] | None = None,
) -> SkillHubProgressOut:
    hubs = hub_rows if hub_rows is not None else repository.list_hubs_for_skill(skill)
    flat = [repository._flatten_hub_row(h) for h in hubs]
    total = len(flat)
    progress = progress_map if progress_map is not None else repository.get_user_progress_map(user_id)
    completed = sum(
        1
        for h in flat
        if progress.get(str(h["id"]), {}).get("status") == "completed"
    )
    mock = mock_row if mock_row is not None else repository.get_skill_full_mock(skill)
    configured = int(mock.get("unlock_requires_sets") or 12) if mock else 12
    required = _effective_required(catalog_total=total, configured=configured)
    mock_test_id = str(mock["mock_test_id"]) if mock and mock.get("mock_test_id") else None
    return SkillHubProgressOut(
        skill=skill,  # type: ignore[arg-type]
        completed_count=completed,
        total_count=total,
        required_for_mock=required,
        mock_unlocked=completed >= required and total > 0,
        mock_test_id=mock_test_id,
    )


def all_skill_progress(user_id: UUID) -> PracticeProgressOut:
    return PracticeProgressOut(
        skills=list(hub_progress_map(user_id).values())
    )


def hub_progress_map(user_id: UUID) -> dict[str, SkillHubProgressOut]:
    """Batched: 1 hubs query + 1 progress + 1 mocks (not 4×3)."""
    hub_prog, _, _ = practice_profile_bundle(user_id)
    return hub_prog


def practice_profile_bundle(
    user_id: UUID,
) -> tuple[
    dict[str, SkillHubProgressOut],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]:
    """Shared snapshot for learning profile: hub progress + rewrite inputs."""
    grouped = repository.list_all_hubs_grouped()
    progress = repository.get_user_progress_map(user_id)
    mocks = {
        str(m.get("skill") or ""): m for m in repository.list_skill_full_mocks()
    }
    hub_prog = {
        s: skill_progress(
            user_id=user_id,
            skill=s,
            progress_map=progress,
            hub_rows=grouped.get(s) or [],
            mock_row=mocks.get(s),
        )
        for s in SKILLS
    }
    return hub_prog, progress, grouped


def mock_unlock_status(*, user_id: UUID, skill: str) -> MockUnlockOut:
    if skill not in SKILLS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid skill")
    prog = skill_progress(user_id=user_id, skill=skill)
    return MockUnlockOut(
        skill=skill,  # type: ignore[arg-type]
        unlocked=prog.mock_unlocked,
        completed=prog.completed_count,
        required=prog.required_for_mock,
        mock_test_id=prog.mock_test_id,
    )


def list_hubs_with_progress(*, user_id: UUID, skill: str) -> list[PracticeHubOut]:
    if skill not in SKILLS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid skill")
    progress = repository.get_user_progress_map(user_id)
    rows = repository.list_hubs_for_skill(skill)
    allowed = accessible_hub_ids_for_skill(
        user_id=user_id, skill=skill, progress_map=progress
    )
    out: list[PracticeHubOut] = []
    for row in rows:
        flat = repository._flatten_hub_row(row)
        hub_id = str(flat["id"])
        prog = progress.get(hub_id, {})
        completed_at = prog.get("completed_at")
        is_accessible = hub_id in allowed
        out.append(
            PracticeHubOut(
                id=hub_id,
                slug=flat["slug"],
                skill=flat["skill"],  # type: ignore[arg-type]
                bank_number=flat["bank_number"],
                set_number=flat["set_number"],
                title=flat["title"],
                estimated_min=flat["estimated_min"],
                sort_order=flat["sort_order"],
                status=prog.get("status") or "pending",  # type: ignore[arg-type]
                completed_at=datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                if isinstance(completed_at, str)
                else completed_at,
                accessible=is_accessible,
                locked_reason=None if is_accessible else LOCKED_HUB_MESSAGE,
            )
        )
    return out


def get_hub_detail(*, user_id: UUID, hub_id: str) -> PracticeHubDetailOut:
    flat = assert_hub_accessible(user_id=user_id, hub_id=hub_id)
    progress = repository.get_user_progress_map(user_id).get(str(hub_id), {})
    completed_at = progress.get("completed_at")
    videos = [
        PracticeVideo(**v) if isinstance(v, dict) else PracticeVideo()
        for v in (flat.get("videos") or [])
    ]
    return PracticeHubDetailOut(
        id=flat["id"],
        slug=flat["slug"],
        skill=flat["skill"],  # type: ignore[arg-type]
        bank_number=flat["bank_number"],
        set_number=flat["set_number"],
        title=flat["title"],
        estimated_min=flat["estimated_min"],
        sort_order=flat["sort_order"],
        status=progress.get("status") or "pending",  # type: ignore[arg-type]
        completed_at=datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        if isinstance(completed_at, str)
        else completed_at,
        accessible=True,
        locked_reason=None,
        videos=videos,
        practice_prompt=flat.get("practice_prompt") or "",
        submit_config=flat.get("submit_config") or {},
    )


def complete_hub(*, user_id: UUID, hub_id: str) -> HubCompleteOut:
    flat = assert_hub_accessible(user_id=user_id, hub_id=hub_id)
    saved = repository.upsert_hub_completed(user_id=user_id, hub_id=hub_id)
    skill = flat["skill"]
    prog = skill_progress(user_id=user_id, skill=skill)
    completed_at = saved.get("completed_at")
    return HubCompleteOut(
        hub_id=str(hub_id),
        status="completed",
        completed_at=datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        if isinstance(completed_at, str)
        else completed_at,
        skill_progress=prog,
    )


def start_hub_exercise(
    *, user_id: UUID, hub_id: str, part: int | None = None
) -> Any:
    from app.practice.schemas import (
        BankExerciseQuestionOut,
        BankExerciseSectionOut,
        ExerciseStartOut,
    )
    from app.db.supabase_client import get_supabase

    flat = assert_hub_accessible(user_id=user_id, hub_id=hub_id)
    set_id = flat.get("set_id")
    skill = flat.get("skill")
    if not set_id or skill not in SKILLS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Hub has no practice set content.",
        )
    sb = get_supabase()
    sections = (
        sb.table("bank_sections")
        .select(
            "id, part, module, title, instructions, audio_key, passage_text, image_url"
        )
        .eq("practice_set_id", set_id)
        .order("part")
        .execute()
    ).data or []
    if not sections:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No question bank content for this hub yet.",
        )
    chosen = None
    if part is not None:
        for sec in sections:
            if int(sec["part"]) == int(part):
                chosen = sec
                break
    if chosen is None:
        chosen = sections[0]
    section_id = str(chosen["id"])
    qrows = (
        sb.table("bank_questions")
        .select(
            "id, question_number, question_type, prompt, options, correct_answer"
        )
        .eq("section_id", section_id)
        .order("question_number")
        .execute()
    ).data or []
    if not qrows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Bank section has no questions.",
        )
    # Abandon prior in-progress for this hub
    sb.table("practice_exercise_attempts").update(
        {"status": "abandoned"}
    ).eq("user_id", str(user_id)).eq("hub_id", str(hub_id)).eq(
        "status", "in_progress"
    ).execute()
    inserted = (
        sb.table("practice_exercise_attempts")
        .insert(
            {
                "user_id": str(user_id),
                "hub_id": str(hub_id),
                "practice_set_id": set_id,
                "section_id": section_id,
                "part": int(chosen["part"]),
                "status": "in_progress",
            }
        )
        .execute()
    ).data or []
    if not inserted:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not start exercise attempt.",
        )
    attempt_id = str(inserted[0]["id"])
    questions = [
        BankExerciseQuestionOut(
            id=str(q["id"]),
            question_number=int(q["question_number"]),
            question_type=str(q["question_type"]),
            prompt=str(q.get("prompt") or ""),
            options=q.get("options"),
            correct_answer=None,  # never leak to client on start for objective skills
        )
        for q in qrows
    ]
    # Writing/speaking don't need hidden answers; L/R hide correct_answer
    return ExerciseStartOut(
        attempt_id=attempt_id,
        hub_id=str(hub_id),
        practice_set_id=set_id,
        skill=skill,  # type: ignore[arg-type]
        part=int(chosen["part"]),
        section=BankExerciseSectionOut(
            section_id=section_id,
            part=int(chosen["part"]),
            module=str(chosen.get("module") or skill),  # type: ignore[arg-type]
            title=chosen.get("title"),
            instructions=chosen.get("instructions"),
            audio_key=chosen.get("audio_key"),
            passage_text=chosen.get("passage_text"),
            image_url=chosen.get("image_url"),
            questions=questions,
        ),
    )


def submit_hub_exercise(
    *,
    user_id: UUID,
    hub_id: str,
    attempt_id: str,
    answers: dict[str, Any],
    mark_hub_complete: bool = True,
) -> Any:
    from app.practice.schemas import ExerciseSubmitOut
    from app.db.supabase_client import get_supabase

    assert_hub_accessible(user_id=user_id, hub_id=hub_id)

    sb = get_supabase()
    rows = (
        sb.table("practice_exercise_attempts")
        .select("*")
        .eq("id", attempt_id)
        .eq("user_id", str(user_id))
        .eq("hub_id", str(hub_id))
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Attempt not found")
    attempt = rows[0]
    if attempt.get("status") != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Attempt is not in progress")

    section_id = attempt.get("section_id")
    score: dict[str, Any] | None = None
    if section_id:
        qrows = (
            sb.table("bank_questions")
            .select("id, correct_answer, question_type")
            .eq("section_id", str(section_id))
            .execute()
        ).data or []
        # Score objective items when correct_answer present
        total = 0
        correct = 0
        for q in qrows:
            key = str(q["id"])
            expected = (q.get("correct_answer") or "").strip()
            if not expected:
                continue
            total += 1
            given = answers.get(key)
            given_s = (
                str(given).strip()
                if given is not None
                else ""
            )
            # Accept primary or slash-alternates
            alts = [p.strip().lower() for p in expected.split("/") if p.strip()]
            if given_s.lower() in alts or given_s.lower() == expected.lower():
                correct += 1
        if total:
            score = {
                "correct": correct,
                "total": total,
                "percent": round(100.0 * correct / total, 1),
            }

    now = datetime.now(UTC).isoformat()
    sb.table("practice_exercise_attempts").update(
        {
            "status": "completed",
            "answers": answers,
            "score": score,
            "completed_at": now,
        }
    ).eq("id", attempt_id).execute()

    hub_completed = False
    prog = None
    if mark_hub_complete:
        done = complete_hub(user_id=user_id, hub_id=hub_id)
        hub_completed = True
        prog = done.skill_progress

    return ExerciseSubmitOut(
        attempt_id=attempt_id,
        status="completed",
        score=score,
        hub_completed=hub_completed,
        skill_progress=prog,
    )


def assert_skill_mock_access(*, user_id: UUID, skill: str) -> None:
    """Raise 403 if skill full mock is not unlocked."""
    if skill not in SKILLS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid skill")
    status_out = mock_unlock_status(user_id=user_id, skill=skill)
    if not status_out.unlocked:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Complete all required practice sets to unlock this mock.",
                "skill": skill,
                "completed": status_out.completed,
                "required": status_out.required,
            },
        )
