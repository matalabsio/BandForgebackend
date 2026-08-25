"""Speaking Skill practice access + hard sequential unlock."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.practice import service
from app.practice.access import resolve_practice_skill_access
from app.practice.speaking_skill_course import (
    LOCKED_HUB_MESSAGE,
    accessible_speaking_skill_hub_ids,
    assert_speaking_skill_hub_accessible,
)
from app.security.entitlements import Entitlements

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")


def _ent(
    *,
    fsp: bool = False,
    speaking_skill: bool = False,
    writing_skill: bool = False,
    speaking: bool | None = None,
    writing: bool = False,
) -> Entitlements:
    if speaking is None:
        speaking = fsp or speaking_skill
    return {
        "plans": (
            (["full_skill_program"] if fsp else [])
            + (["speaking_skill"] if speaking_skill else [])
            + (["writing_skill"] if writing_skill else [])
        ),
        "skills": {
            "listening": fsp,
            "reading": fsp,
            "writing": writing or writing_skill or fsp,
            "speaking": speaking,
        },
        "writing_skill": writing_skill,
        "speaking_skill": speaking_skill,
        "full_skill_program": fsp,
    }


def _hub_row(hub_id: str, *, set_number: int = 1) -> dict:
    return {
        "id": hub_id,
        "slug": f"speaking-{hub_id}",
        "set_id": f"set-{hub_id}",
        "estimated_min": 15,
        "sort_order": set_number,
        "practice_prompt": "",
        "videos": [],
        "submit_config": {},
        "practice_sets": {
            "id": f"set-{hub_id}",
            "set_number": set_number,
            "title": f"Speaking {hub_id}",
            "status": "published",
            "difficulty": "medium",
            "practice_banks": {
                "skill": "speaking",
                "bank_number": 4,
                "title": "Speaking Bank",
            },
        },
    }


def _course_rows(hub_ids: list[str]) -> list[dict]:
    rows = []
    for i, hid in enumerate(hub_ids, start=1):
        row = _hub_row(hid, set_number=i)
        row["_program_sort_order"] = i
        row["_program_exam_module"] = "both"
        rows.append(row)
    return rows


def test_resolve_access_fsp_and_speaking_skill():
    with patch(
        "app.practice.access.resolve_entitlements",
        return_value=_ent(fsp=True),
    ):
        assert resolve_practice_skill_access(user_id=USER_ID, skill="speaking") == "fsp"
        assert resolve_practice_skill_access(user_id=USER_ID, skill="writing") == "fsp"

    with patch(
        "app.practice.access.resolve_entitlements",
        return_value=_ent(speaking_skill=True),
    ):
        assert (
            resolve_practice_skill_access(user_id=USER_ID, skill="speaking")
            == "speaking_skill"
        )
        with pytest.raises(HTTPException) as exc:
            resolve_practice_skill_access(user_id=USER_ID, skill="writing")
        assert exc.value.status_code == 403


def test_speaking_skill_cannot_access_writing():
    with patch(
        "app.practice.access.resolve_entitlements",
        return_value=_ent(speaking_skill=True),
    ):
        with pytest.raises(HTTPException) as exc:
            resolve_practice_skill_access(user_id=USER_ID, skill="writing")
        assert exc.value.status_code == 403


def test_hard_sequence_list_and_assert():
    rows = _course_rows([f"h{i}" for i in range(1, 13)])
    progress: dict = {}

    with (
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="speaking_skill",
        ),
        patch(
            "app.practice.service.list_speaking_skill_hub_rows",
            return_value=rows,
        ),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value=progress,
        ),
    ):
        listed = service.list_hubs_with_progress(user_id=USER_ID, skill="speaking")
    assert len(listed) == 12
    assert listed[0].accessible is True
    assert listed[1].accessible is False
    assert all(not h.accessible for h in listed[1:])

    ordered = [f"h{i}" for i in range(1, 13)]
    assert accessible_speaking_skill_hub_ids(
        ordered_hub_ids=ordered, progress_map={}
    ) == {"h1"}

    progress["h1"] = {"status": "completed"}
    assert accessible_speaking_skill_hub_ids(
        ordered_hub_ids=ordered, progress_map=progress
    ) == {"h1", "h2"}


def test_completing_hub_n_unlocks_n_plus_1():
    ordered = [f"h{i}" for i in range(1, 5)]
    progress = {hid: {"status": "completed"} for hid in ("h1", "h2")}
    assert accessible_speaking_skill_hub_ids(
        ordered_hub_ids=ordered, progress_map=progress
    ) == {"h1", "h2", "h3"}


def test_deep_link_future_hub_returns_403():
    rows = _course_rows(["h1", "h2", "h3"])
    with (
        patch(
            "app.practice.speaking_skill_course.repository.get_hub_by_id",
            return_value=rows[2],
        ),
        patch(
            "app.practice.speaking_skill_course.list_speaking_skill_hub_rows",
            return_value=rows,
        ),
        patch(
            "app.practice.speaking_skill_course.repository.get_user_progress_map",
            return_value={},
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_speaking_skill_hub_accessible(user_id=USER_ID, hub_id="h3")
        assert exc.value.status_code == 403
        assert exc.value.detail == LOCKED_HUB_MESSAGE


def test_pci_hubs_only_listed():
    rows = _course_rows(["h1", "h2"])
    with (
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="speaking_skill",
        ),
        patch(
            "app.practice.service.list_speaking_skill_hub_rows",
            return_value=rows,
        ),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value={},
        ),
        patch(
            "app.practice.service.repository.list_hubs_for_skill",
        ) as fsp_list,
    ):
        listed = service.list_hubs_with_progress(user_id=USER_ID, skill="speaking")
    assert [h.id for h in listed] == ["h1", "h2"]
    fsp_list.assert_not_called()
