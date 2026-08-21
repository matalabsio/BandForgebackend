"""Practice access policy: FSP vs Writing Skill pack modes.

FSP keeps the existing soft-repeat catalogue path.
Writing Skill uses program_content_items + hard sequential unlock.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.security.entitlements import resolve_entitlements

PracticeAccessMode = Literal["fsp", "writing_skill"]

SKILLS = frozenset({"listening", "reading", "writing", "speaking"})


def has_any_practice_entitlement(user_id: UUID) -> bool:
    ent = resolve_entitlements(user_id)
    if ent["full_skill_program"]:
        return True
    return any(ent["skills"].values())


async def require_practice_access(
    current_user: Annotated[UserPublic, Depends(get_current_user)],
) -> UserPublic:
    """Any skill-practice entitlement (FSP or pack SKUs). Not 'any subscription'."""
    if not has_any_practice_entitlement(current_user.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="An active practice entitlement is required to access practice hubs.",
        )
    return current_user


def resolve_practice_skill_access(*, user_id: UUID, skill: str) -> PracticeAccessMode:
    """Return access mode for a skill, or raise 403.

    FSP wins when present (existing soft-repeat catalogue).
    Writing Skill pack grants writing only via the hard-sequence course path.
    """
    skill = str(skill or "").strip().lower()
    if skill not in SKILLS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid skill")

    ent = resolve_entitlements(user_id)
    if ent["full_skill_program"]:
        return "fsp"

    if not ent["skills"].get(skill):  # type: ignore[arg-type]
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"Your plan does not include {skill} practice.",
        )

    if skill == "writing" and ent["writing_skill"]:
        return "writing_skill"

    # Entitled via some other future pack mapping — treat as denied until wired.
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail=f"Your plan does not include {skill} practice.",
    )
