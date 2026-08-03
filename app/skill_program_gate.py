"""Gate module exam starts that originate from skill-program mock unlock."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

SKILLS = frozenset({"listening", "reading", "writing", "speaking"})


def assert_skill_program_module_start(
    *,
    user_id: UUID,
    skill_context: str | None,
    from_plan: bool = False,
) -> None:
    """When skill_context is set, require Full Skill Program.

    Catalogue skill-mock unlock still needs 12/12 hubs.
    Personalized plan practice (`from_plan`) only needs Full Skill Program —
    daily tasks must open MT Writing/Speaking before mock unlock.
    """
    if not skill_context:
        return
    if skill_context not in SKILLS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Invalid skill_context.",
        )
    from app.security.entitlements import has_full_skill_program
    from app.practice.service import assert_skill_mock_access

    if not has_full_skill_program(user_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Full Skill Program is required for skill mock access.",
        )
    if from_plan:
        return
    assert_skill_mock_access(user_id=user_id, skill=skill_context)
