"""Phase 4: Writing Skill practice access + hard sequential unlock."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.practice import service
from app.practice.access import resolve_practice_skill_access
from app.practice.writing_skill_course import (
    EXAM_MODULE_REQUIRED_DETAIL,
    LOCKED_HUB_MESSAGE,
    accessible_writing_skill_hub_ids,
    assert_writing_skill_hub_accessible,
)
from app.security.entitlements import Entitlements

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
PLAN_ID = "plan_writing"


def _ent(
    *,
    fsp: bool = False,
    writing_skill: bool = False,
    writing: bool | None = None,
    listening: bool = False,
    reading: bool = False,
    speaking: bool = False,
) -> Entitlements:
    if writing is None:
        writing = fsp or writing_skill
    return {
        "plans": (
            (["full_skill_program"] if fsp else [])
            + (["writing_skill"] if writing_skill else [])
        ),
        "skills": {
            "listening": listening or fsp,
            "reading": reading or fsp,
            "writing": writing,
            "speaking": speaking or fsp,
        },
        "writing_skill": writing_skill,
        "speaking_skill": False,
        "full_skill_program": fsp,
    }


def _hub_row(hub_id: str, *, set_number: int = 1) -> dict:
    return {
        "id": hub_id,
        "slug": f"writing-{hub_id}",
        "set_id": f"set-{hub_id}",
        "estimated_min": 25,
        "sort_order": set_number,
        "practice_prompt": "Write",
        "videos": [],
        "submit_config": {},
        "practice_sets": {
            "id": f"set-{hub_id}",
            "set_number": set_number,
            "title": f"Writing {hub_id}",
            "status": "published",
            "difficulty": "medium",
            "practice_banks": {
                "skill": "writing",
                "bank_number": 1,
                "title": "Writing Bank",
            },
        },
    }


def _course_rows(hub_ids: list[str]) -> list[dict]:
    rows = []
    for i, hid in enumerate(hub_ids, start=1):
        row = _hub_row(hid, set_number=i)
        row["_program_sort_order"] = i
        row["_program_exam_module"] = "academic"
        rows.append(row)
    return rows


def test_resolve_access_fsp_and_writing_skill():
    with patch(
        "app.practice.access.resolve_entitlements",
        return_value=_ent(fsp=True),
    ):
        assert resolve_practice_skill_access(user_id=USER_ID, skill="writing") == "fsp"
        assert resolve_practice_skill_access(user_id=USER_ID, skill="listening") == "fsp"

    with patch(
        "app.practice.access.resolve_entitlements",
        return_value=_ent(writing_skill=True),
    ):
        assert (
            resolve_practice_skill_access(user_id=USER_ID, skill="writing")
            == "writing_skill"
        )
        with pytest.raises(HTTPException) as exc:
            resolve_practice_skill_access(user_id=USER_ID, skill="listening")
        assert exc.value.status_code == 403


def test_unrelated_subscription_denied():
    with patch(
        "app.practice.access.resolve_entitlements",
        return_value=_ent(writing=False),
    ):
        with pytest.raises(HTTPException) as exc:
            resolve_practice_skill_access(user_id=USER_ID, skill="writing")
        assert exc.value.status_code == 403


def test_exam_module_null_returns_409_on_list():
    with (
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="writing_skill",
        ),
        patch(
            "app.practice.service.list_writing_skill_hub_rows",
            side_effect=HTTPException(status_code=409, detail=EXAM_MODULE_REQUIRED_DETAIL),
        ),
        patch("app.practice.service.repository.get_user_progress_map", return_value={}),
    ):
        with pytest.raises(HTTPException) as exc:
            service.list_hubs_with_progress(user_id=USER_ID, skill="writing")
        assert exc.value.status_code == 409
        assert "exam_module" in str(exc.value.detail)


def test_hard_sequence_list_and_assert():
    rows = _course_rows(["h1", "h2", "h3", "h5"])
    progress: dict = {}

    with (
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="writing_skill",
        ),
        patch(
            "app.practice.service.list_writing_skill_hub_rows",
            return_value=rows,
        ),
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value=progress,
        ),
    ):
        listed = service.list_hubs_with_progress(user_id=USER_ID, skill="writing")
    assert [h.id for h in listed] == ["h1", "h2", "h3", "h5"]
    assert listed[0].accessible is True
    assert listed[1].accessible is False
    assert listed[2].accessible is False
    assert listed[3].accessible is False

    ordered = ["h1", "h2", "h3", "h5"]
    assert accessible_writing_skill_hub_ids(
        ordered_hub_ids=ordered, progress_map={}
    ) == {"h1"}

    progress["h1"] = {"status": "completed"}
    assert accessible_writing_skill_hub_ids(
        ordered_hub_ids=ordered, progress_map=progress
    ) == {"h1", "h2"}

    progress["h2"] = {"status": "completed"}
    assert accessible_writing_skill_hub_ids(
        ordered_hub_ids=ordered, progress_map=progress
    ) == {"h1", "h2", "h3"}


def test_deep_link_future_hub_returns_403():
    rows = _course_rows(["h1", "h2", "h3"])
    with (
        patch(
            "app.practice.writing_skill_course.repository.get_hub_by_id",
            return_value=rows[2],
        ),
        patch(
            "app.practice.writing_skill_course.list_writing_skill_hub_rows",
            return_value=rows,
        ),
        patch(
            "app.practice.writing_skill_course.repository.get_user_progress_map",
            return_value={},
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_writing_skill_hub_accessible(user_id=USER_ID, hub_id="h3")
        assert exc.value.status_code == 403
        assert exc.value.detail == LOCKED_HUB_MESSAGE


def test_unattached_hub_returns_403():
    rows = _course_rows(["h1", "h2"])
    outsider = _hub_row("hx", set_number=9)
    with (
        patch(
            "app.practice.writing_skill_course.repository.get_hub_by_id",
            return_value=outsider,
        ),
        patch(
            "app.practice.writing_skill_course.list_writing_skill_hub_rows",
            return_value=rows,
        ),
        patch(
            "app.practice.writing_skill_course.repository.get_user_progress_map",
            return_value={},
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_writing_skill_hub_accessible(user_id=USER_ID, hub_id="hx")
        assert exc.value.status_code == 403
        assert "not part of your Writing Skill" in str(exc.value.detail)


def test_assert_hub_accessible_routes_writing_skill_to_hard_sequence():
    with (
        patch(
            "app.practice.service.repository.get_hub_by_id",
            return_value=_hub_row("h2"),
        ),
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="writing_skill",
        ),
        patch(
            "app.practice.service.assert_writing_skill_hub_accessible",
            side_effect=HTTPException(status_code=403, detail=LOCKED_HUB_MESSAGE),
        ) as hard,
    ):
        with pytest.raises(HTTPException) as exc:
            service.assert_hub_accessible(user_id=USER_ID, hub_id="h2")
        assert exc.value.status_code == 403
        hard.assert_called_once()


def test_fsp_soft_repeat_still_allows_non_sequential_hub():
    detail = _hub_row("h2")
    detail["practice_sets"]["practice_banks"]["skill"] = "listening"
    with (
        patch("app.practice.service.repository.get_hub_by_id", return_value=detail),
        patch("app.practice.service.repository.is_hub_assignable", return_value=True),
        patch("app.practice.service.repository.get_user_progress_map", return_value={}),
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="fsp",
        ),
        patch(
            "app.practice.catalog.get_ordered_hub_ids_by_skill",
            return_value={"listening": ["h1", "h2"]},
        ),
    ):
        flat = service.assert_hub_accessible(user_id=USER_ID, hub_id="h2")
    assert flat["id"] == "h2"


def test_track_filter_uses_program_items_modules():
    from app.practice.writing_skill_course import list_writing_skill_program_items

    with patch("app.db.supabase_client.get_supabase") as get_sb:
        table = get_sb.return_value.table.return_value
        table.select.return_value = table
        table.eq.return_value = table
        table.in_.return_value = table
        table.order.return_value = table
        table.execute.return_value.data = [
            {
                "item_id": "a1",
                "exam_module": "academic",
                "sort_order": 1,
                "is_active": True,
            },
            {
                "item_id": "b1",
                "exam_module": "both",
                "sort_order": 2,
                "is_active": True,
            },
        ]
        out = list_writing_skill_program_items(plan_id=PLAN_ID, exam_module="academic")
    assert {i["item_id"] for i in out} == {"a1", "b1"}


def test_complete_hub_idempotent_under_writing_skill():
    from app.practice.schemas import SkillHubProgressOut

    flat = {
        "id": "h1",
        "skill": "writing",
        "slug": "w",
        "bank_number": 1,
        "set_number": 1,
        "title": "T",
        "estimated_min": 25,
        "sort_order": 1,
    }
    with (
        patch(
            "app.practice.service.assert_hub_accessible",
            return_value=flat,
        ),
        patch(
            "app.practice.service.repository.upsert_hub_completed",
            return_value={"completed_at": "2026-08-21T00:00:00+00:00"},
        ),
        patch(
            "app.practice.service._skill_progress_for_access_mode",
            return_value=SkillHubProgressOut(
                skill="writing",
                completed_count=1,
                total_count=3,
                required_for_mock=0,
                mock_unlocked=False,
            ),
        ),
    ):
        first = service.complete_hub(user_id=USER_ID, hub_id="h1")
        second = service.complete_hub(user_id=USER_ID, hub_id="h1")
    assert first.status == "completed"
    assert second.status == "completed"


def test_writing_skill_list_ignores_fsp_catalog():
    fsp_hubs = [_hub_row("fsp1"), _hub_row("fsp2")]
    course = _course_rows(["c1", "c2"])
    with (
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="writing_skill",
        ),
        patch(
            "app.practice.service.list_writing_skill_hub_rows",
            return_value=course,
        ),
        patch(
            "app.practice.service.repository.list_hubs_for_skill",
            return_value=fsp_hubs,
        ) as fsp_list,
        patch(
            "app.practice.service.repository.get_user_progress_map",
            return_value={},
        ),
    ):
        out = service.list_hubs_with_progress(user_id=USER_ID, skill="writing")
    fsp_list.assert_not_called()
    assert [h.id for h in out] == ["c1", "c2"]
