"""Business logic for practice hubs and mock unlock."""

from __future__ import annotations

from datetime import datetime
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


def _effective_required(*, catalog_total: int, configured: int) -> int:
    if catalog_total <= 0:
        return configured
    if catalog_total < configured:
        return catalog_total
    return configured


def skill_progress(*, user_id: UUID, skill: str) -> SkillHubProgressOut:
    hubs = repository.list_hubs_for_skill(skill)
    flat = [repository._flatten_hub_row(h) for h in hubs]
    total = len(flat)
    completed = repository.count_completed_for_skill(user_id=user_id, skill=skill)
    mock_row = repository.get_skill_full_mock(skill)
    configured = int(mock_row.get("unlock_requires_sets") or 12) if mock_row else 12
    required = _effective_required(catalog_total=total, configured=configured)
    mock_test_id = str(mock_row["mock_test_id"]) if mock_row and mock_row.get("mock_test_id") else None
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
        skills=[skill_progress(user_id=user_id, skill=s) for s in SKILLS]
    )


def hub_progress_map(user_id: UUID) -> dict[str, SkillHubProgressOut]:
    return {s: skill_progress(user_id=user_id, skill=s) for s in SKILLS}


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
    out: list[PracticeHubOut] = []
    for row in rows:
        flat = repository._flatten_hub_row(row)
        prog = progress.get(flat["id"], {})
        completed_at = prog.get("completed_at")
        out.append(
            PracticeHubOut(
                id=flat["id"],
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
            )
        )
    return out


def get_hub_detail(*, user_id: UUID, hub_id: str) -> PracticeHubDetailOut:
    row = repository.get_hub_by_id(hub_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Hub not found")
    flat = repository._flatten_hub_row(row)
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
        videos=videos,
        practice_prompt=flat.get("practice_prompt") or "",
        submit_config=flat.get("submit_config") or {},
    )


def complete_hub(*, user_id: UUID, hub_id: str) -> HubCompleteOut:
    row = repository.get_hub_by_id(hub_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Hub not found")
    flat = repository._flatten_hub_row(row)
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
