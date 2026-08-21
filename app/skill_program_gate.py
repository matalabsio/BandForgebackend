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
    mock_test_id: UUID | None = None,
) -> dict | None:
    """When skill_context is set, require FSP or Writing Skill (writing only).

    FSP: catalogue skill-mock unlock still needs 12/12 hubs (unless from_plan).
    Writing Skill: course-complete + quota + allotted mock (when mock_test_id given).

    Returns Writing Skill access context when pack rules apply; else None.
    """
    if not skill_context:
        return None
    if skill_context not in SKILLS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Invalid skill_context.",
        )
    from app.security.entitlements import has_full_skill_program, resolve_entitlements
    from app.practice.service import assert_skill_mock_access

    if has_full_skill_program(user_id):
        if from_plan:
            return None
        assert_skill_mock_access(user_id=user_id, skill=skill_context)
        return None

    ent = resolve_entitlements(user_id)
    if skill_context == "writing" and ent["writing_skill"]:
        from app.practice.writing_skill_mock import (
            assert_writing_skill_mock_access,
            assert_writing_skill_mock_for_test,
        )

        if mock_test_id is not None:
            return assert_writing_skill_mock_for_test(
                user_id=user_id, mock_test_id=mock_test_id
            )
        return assert_writing_skill_mock_access(user_id=user_id)

    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail="Full Skill Program is required for skill mock access.",
    )
