"""Phase 5: Writing Skill exam_module track + mock quota."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.practice.writing_skill_course import EXAM_MODULE_REQUIRED_DETAIL
from app.practice.writing_skill_mock import (
    COURSE_INCOMPLETE_DETAIL,
    MOCK_NOT_ALLOTTED_DETAIL,
    MOCK_QUOTA_EXHAUSTED_DETAIL,
    assert_writing_skill_mock_access,
    assert_writing_skill_mock_for_test,
    consume_writing_skill_mock_quota,
    writing_skill_course_completion,
    writing_skill_mock_unlock_status,
)
from app.practice.writing_skill_track import (
    TRACK_LOCKED_DETAIL,
    set_writing_skill_exam_module,
)
from app.security.entitlements import Entitlements, enforce_premium_mock_flags
from app.auth.schemas import UserPublic

USER_ID = UUID("00000000-0000-4000-8000-0000000000a1")
USAGE_ID = "usage-1"
PLAN_ID = "plan-ws"
MOCK_ACAD = "11111111-1111-4111-8111-111111111111"
MOCK_GT = "22222222-2222-4222-8222-222222222222"
OTHER_MOCK = "33333333-3333-4333-8333-333333333333"


def _ent(*, writing_skill: bool = True, fsp: bool = False) -> Entitlements:
    return {
        "plans": (["writing_skill"] if writing_skill else [])
        + (["full_skill_program"] if fsp else []),
        "skills": {
            "listening": fsp,
            "reading": fsp,
            "writing": writing_skill or fsp,
            "speaking": fsp,
        },
        "writing_skill": writing_skill,
        "speaking_skill": False,
        "full_skill_program": fsp,
    }


def _usage(**overrides):
    base = {
        "id": USAGE_ID,
        "user_id": str(USER_ID),
        "subscription_id": "sub-1",
        "plan_id": PLAN_ID,
        "exam_module": "academic",
        "mocks_granted": 1,
        "mocks_used": 0,
    }
    base.update(overrides)
    return base


def _ctx(**usage_overrides):
    usage = _usage(**usage_overrides)
    return {
        "subscription_id": "sub-1",
        "plan_id": PLAN_ID,
        "usage": usage,
        "exam_module": usage.get("exam_module"),
    }


def _user() -> UserPublic:
    return UserPublic(
        id=USER_ID,
        email="s@example.com",
        full_name="S",
        phone="9876543210",
        target_band=7.0,
    )


# --- Track selection ---


def test_set_exam_module_denied_without_entitlement():
    with patch(
        "app.practice.writing_skill_track.resolve_entitlements",
        return_value=_ent(writing_skill=False),
    ):
        with pytest.raises(HTTPException) as exc:
            set_writing_skill_exam_module(user_id=USER_ID, exam_module="academic")
        assert exc.value.status_code == 403


def test_set_exam_module_null_to_academic():
    with (
        patch(
            "app.practice.writing_skill_track.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_track.get_writing_skill_course_context",
            return_value=_ctx(exam_module=None),
        ),
        patch(
            "app.payments.repository.set_user_program_exam_module_atomic",
            return_value=_usage(exam_module="academic"),
        ),
        patch(
            "app.practice.writing_skill_track._sync_profile_exam_module"
        ) as sync,
    ):
        out = set_writing_skill_exam_module(user_id=USER_ID, exam_module="academic")
    assert out["exam_module"] == "academic"
    assert out["changed"] is True
    sync.assert_called_once()


def test_set_exam_module_idempotent():
    with (
        patch(
            "app.practice.writing_skill_track.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_track.get_writing_skill_course_context",
            return_value=_ctx(exam_module="academic"),
        ),
        patch(
            "app.practice.writing_skill_track._sync_profile_exam_module"
        ),
    ):
        out = set_writing_skill_exam_module(user_id=USER_ID, exam_module="academic")
    assert out["changed"] is False


def test_set_exam_module_change_blocked_after_progress():
    with (
        patch(
            "app.practice.writing_skill_track.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_track.get_writing_skill_course_context",
            return_value=_ctx(exam_module="academic"),
        ),
        patch(
            "app.practice.writing_skill_track.writing_skill_progress_started",
            return_value=True,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            set_writing_skill_exam_module(
                user_id=USER_ID, exam_module="general_training"
            )
        assert exc.value.status_code == 409
        assert exc.value.detail == TRACK_LOCKED_DETAIL


def test_set_exam_module_change_allowed_before_progress():
    with (
        patch(
            "app.practice.writing_skill_track.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_track.get_writing_skill_course_context",
            return_value=_ctx(exam_module="academic"),
        ),
        patch(
            "app.practice.writing_skill_track.writing_skill_progress_started",
            return_value=False,
        ),
        patch(
            "app.payments.repository.set_user_program_exam_module_atomic",
            return_value=_usage(exam_module="general_training"),
        ),
        patch("app.practice.writing_skill_track._sync_profile_exam_module"),
    ):
        out = set_writing_skill_exam_module(
            user_id=USER_ID, exam_module="general_training"
        )
    assert out["exam_module"] == "general_training"
    assert out["changed"] is True


# --- Course completion / mock access ---


def test_course_completion_from_program_pool_not_hardcoded_12():
    hubs = [{"id": f"h{i}"} for i in range(3)]

    def flatten(row):
        return {"id": row["id"]}

    with (
        patch(
            "app.practice.writing_skill_mock.list_writing_skill_hub_rows",
            return_value=hubs,
        ),
        patch(
            "app.practice.repository.get_user_progress_map",
            return_value={"h0": {"status": "completed"}, "h1": {"status": "completed"}},
        ),
        patch("app.practice.repository._flatten_hub_row", side_effect=flatten),
    ):
        completed, total, _ = writing_skill_course_completion(user_id=USER_ID)
    assert total == 3
    assert completed == 2


def test_mock_denied_when_incomplete():
    with (
        patch(
            "app.practice.writing_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.get_writing_skill_course_context",
            return_value=_ctx(),
        ),
        patch(
            "app.practice.writing_skill_mock.writing_skill_course_completion",
            return_value=(2, 3, []),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_writing_skill_mock_access(user_id=USER_ID)
        assert exc.value.status_code == 403
        assert COURSE_INCOMPLETE_DETAIL in str(exc.value.detail)


def test_mock_allowed_when_complete_with_quota():
    with (
        patch(
            "app.practice.writing_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.get_writing_skill_course_context",
            return_value=_ctx(),
        ),
        patch(
            "app.practice.writing_skill_mock.writing_skill_course_completion",
            return_value=(3, 3, []),
        ),
        patch(
            "app.practice.writing_skill_mock.resolve_writing_skill_mock_test_id",
            return_value=MOCK_ACAD,
        ),
    ):
        access = assert_writing_skill_mock_access(user_id=USER_ID)
    assert access["mock_test_id"] == MOCK_ACAD


def test_wrong_mock_denied():
    with (
        patch(
            "app.practice.writing_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.get_writing_skill_course_context",
            return_value=_ctx(),
        ),
        patch(
            "app.practice.writing_skill_mock.writing_skill_course_completion",
            return_value=(3, 3, []),
        ),
        patch(
            "app.practice.writing_skill_mock.resolve_writing_skill_mock_test_id",
            return_value=MOCK_ACAD,
        ),
        patch(
            "app.practice.writing_skill_mock.user_has_attempt_for_mock",
            return_value=False,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_writing_skill_mock_for_test(
                user_id=USER_ID, mock_test_id=OTHER_MOCK
            )
        assert exc.value.status_code == 403
        assert MOCK_NOT_ALLOTTED_DETAIL in str(exc.value.detail)


def test_quota_exhausted_denied():
    with (
        patch(
            "app.practice.writing_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.get_writing_skill_course_context",
            return_value=_ctx(mocks_used=1),
        ),
        patch(
            "app.practice.writing_skill_mock.writing_skill_course_completion",
            return_value=(3, 3, []),
        ),
        patch(
            "app.practice.writing_skill_mock.resolve_writing_skill_mock_test_id",
            return_value=MOCK_ACAD,
        ),
        patch(
            "app.practice.writing_skill_mock.user_has_attempt_for_mock",
            return_value=False,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            assert_writing_skill_mock_for_test(
                user_id=USER_ID, mock_test_id=MOCK_ACAD
            )
        assert exc.value.status_code == 403
        assert MOCK_QUOTA_EXHAUSTED_DETAIL in str(exc.value.detail)


def test_resume_allowed_after_quota_used():
    with (
        patch(
            "app.practice.writing_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.get_writing_skill_course_context",
            return_value=_ctx(mocks_used=1),
        ),
        patch(
            "app.practice.writing_skill_mock.writing_skill_course_completion",
            return_value=(3, 3, []),
        ),
        patch(
            "app.practice.writing_skill_mock.resolve_writing_skill_mock_test_id",
            return_value=MOCK_ACAD,
        ),
        patch(
            "app.practice.writing_skill_mock.user_has_attempt_for_mock",
            return_value=True,
        ),
    ):
        access = assert_writing_skill_mock_for_test(
            user_id=USER_ID, mock_test_id=MOCK_ACAD
        )
    assert access["should_consume"] is False


def test_atomic_consume_success_and_exhaust():
    with patch(
        "app.payments.repository.consume_user_program_mock_quota_atomic",
        return_value=_usage(mocks_used=1),
    ):
        row = consume_writing_skill_mock_quota(usage_id=USAGE_ID)
        assert row["mocks_used"] == 1

    with patch(
        "app.payments.repository.consume_user_program_mock_quota_atomic",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc:
            consume_writing_skill_mock_quota(usage_id=USAGE_ID)
        assert exc.value.status_code == 403


def test_concurrent_consume_only_one_succeeds():
    """Simulate two atomic consume calls — second returns None."""
    results = [_usage(mocks_used=1), None]

    def _consume(**_kwargs):
        return results.pop(0)

    with patch(
        "app.payments.repository.consume_user_program_mock_quota_atomic",
        side_effect=_consume,
    ):
        first = consume_writing_skill_mock_quota(usage_id=USAGE_ID)
        assert first["mocks_used"] == 1
        with pytest.raises(HTTPException) as exc:
            consume_writing_skill_mock_quota(usage_id=USAGE_ID)
        assert exc.value.status_code == 403


def test_unlock_status_409_without_exam_module():
    with (
        patch(
            "app.practice.writing_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.get_writing_skill_course_context",
            return_value=_ctx(exam_module=None),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            writing_skill_mock_unlock_status(user_id=USER_ID)
        assert exc.value.status_code == 409
        assert EXAM_MODULE_REQUIRED_DETAIL in str(exc.value.detail)


def test_unlock_status_includes_exam_module_additive():
    with (
        patch(
            "app.practice.writing_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.get_writing_skill_course_context",
            return_value=_ctx(exam_module="academic"),
        ),
        patch(
            "app.practice.writing_skill_mock.writing_skill_course_completion",
            return_value=(3, 12, []),
        ),
        patch(
            "app.practice.writing_skill_mock.resolve_writing_skill_mock_test_id",
            side_effect=HTTPException(status_code=404, detail="missing"),
        ),
    ):
        out = writing_skill_mock_unlock_status(user_id=USER_ID)
    assert out["exam_module"] == "academic"
    assert out["completed"] == 3
    assert out["required"] == 12
    assert out["unlocked"] is False


def test_premium_gate_blocks_unrelated_mock_for_writing_skill():
    with (
        patch(
            "app.security.entitlements.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.assert_writing_skill_mock_for_test",
            side_effect=HTTPException(
                status_code=403,
                detail="Writing Skill mock access required for this mock.",
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            enforce_premium_mock_flags(
                user=_user(),
                mock_test_id=UUID(OTHER_MOCK),
                flags={"is_free": False, "is_diagnostic": False},
                subscription_active=True,
            )
        assert exc.value.status_code == 403


def test_premium_gate_allows_allotted_writing_skill_mock():
    with (
        patch(
            "app.security.entitlements.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.assert_writing_skill_mock_for_test",
            return_value={
                "usage_id": USAGE_ID,
                "mock_test_id": MOCK_ACAD,
                "should_consume": True,
            },
        ) as assert_ws,
    ):
        enforce_premium_mock_flags(
            user=_user(),
            mock_test_id=UUID(MOCK_ACAD),
            flags={"is_free": False, "is_diagnostic": False},
            subscription_active=True,
        )
    assert_ws.assert_called_once()


def test_premium_gate_blocks_incomplete_course_for_writing_skill_pack():
    """B1: allotment alone must not open L/R/S starts before course complete."""
    with (
        patch(
            "app.security.entitlements.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.assert_writing_skill_mock_for_test",
            side_effect=HTTPException(
                status_code=403,
                detail={
                    "message": "Complete all Writing Skill practice sets to unlock your mock.",
                    "completed": 0,
                    "required": 12,
                },
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            enforce_premium_mock_flags(
                user=_user(),
                mock_test_id=UUID(MOCK_ACAD),
                flags={"is_free": False, "is_diagnostic": False},
                subscription_active=True,
            )
        assert exc.value.status_code == 403


def test_unlock_status_hides_mock_id_while_locked():
    with (
        patch(
            "app.practice.writing_skill_mock.resolve_entitlements",
            return_value=_ent(),
        ),
        patch(
            "app.practice.writing_skill_mock.get_writing_skill_course_context",
            return_value=_ctx(),
        ),
        patch(
            "app.practice.writing_skill_mock.writing_skill_course_completion",
            return_value=(3, 12, []),
        ),
        patch(
            "app.practice.writing_skill_mock.resolve_writing_skill_mock_test_id",
            return_value=MOCK_ACAD,
        ) as resolve_mock,
    ):
        out = writing_skill_mock_unlock_status(user_id=USER_ID)
    assert out["unlocked"] is False
    assert out["mock_test_id"] is None
    resolve_mock.assert_not_called()


def test_fsp_premium_gate_unchanged_uses_subscription():
    with (
        patch(
            "app.security.entitlements.resolve_entitlements",
            return_value=_ent(writing_skill=False, fsp=True),
        ),
        patch(
            "app.security.entitlements.has_active_subscription",
            return_value=True,
        ) as sub,
    ):
        enforce_premium_mock_flags(
            user=_user(),
            mock_test_id=UUID(OTHER_MOCK),
            flags={"is_free": False, "is_diagnostic": False},
            subscription_active=None,
        )
    sub.assert_called_once()


def test_mock_content_resolves_by_track():
    from app.practice.writing_skill_mock import list_writing_skill_mock_items

    with patch("app.db.supabase_client.get_supabase") as get_sb:
        table = get_sb.return_value.table.return_value
        table.select.return_value = table
        table.eq.return_value = table
        table.in_.return_value = table
        table.order.return_value = table
        table.execute.return_value.data = [
            {
                "item_id": MOCK_ACAD,
                "exam_module": "academic",
                "sort_order": 1,
                "is_active": True,
            }
        ]
        items = list_writing_skill_mock_items(
            plan_id=PLAN_ID, exam_module="academic"
        )
    assert items[0]["item_id"] == MOCK_ACAD
    table.in_.assert_called()


def test_migration_defines_atomic_quota_rpc():
    from pathlib import Path

    sql = Path(
        "supabase/migrations/20260821130000_writing_skill_track_mock_quota.sql"
    ).read_text()
    assert "consume_user_program_mock_quota" in sql
    assert "mocks_used = mocks_used + 1" in sql
    assert "mocks_used < mocks_granted" in sql
    assert "set_user_program_exam_module" in sql


def test_writing_skill_course_uses_usage_exam_module_not_users_profile():
    """users.exam_module must not override Writing Skill purchased track."""
    from app.practice.writing_skill_course import list_writing_skill_hub_rows

    # Profile preference Academic; purchased Writing Skill track is GT.
    ctx = _ctx(exam_module="general_training")
    hub_row = {
        "id": "hub-gt-1",
        "skill": "writing",
        "status": "published",
        "practice_set_id": "set-1",
        "set_status": "published",
        "set_number": 1,
        "title": "GT Letter 1",
        "difficulty": "medium",
    }

    with (
        patch(
            "app.practice.writing_skill_course.get_writing_skill_course_context",
            return_value=ctx,
        ),
        patch(
            "app.practice.writing_skill_course.list_writing_skill_program_items",
            return_value=[
                {
                    "item_id": "hub-gt-1",
                    "exam_module": "general_training",
                    "sort_order": 1,
                    "is_active": True,
                    "item_type": "practice_hub",
                }
            ],
        ) as list_items,
        patch(
            "app.practice.repository.get_hub_by_id",
            return_value=hub_row,
        ),
        patch(
            "app.practice.repository.is_hub_assignable",
            return_value=True,
        ),
        patch(
            "app.practice.repository._flatten_hub_row",
            side_effect=lambda r: {
                "id": r["id"],
                "skill": "writing",
                "status": "published",
            },
        ),
    ):
        rows = list_writing_skill_hub_rows(user_id=USER_ID)

    list_items.assert_called_once_with(
        plan_id=PLAN_ID, exam_module="general_training"
    )
    assert len(rows) == 1
    assert rows[0]["_program_exam_module"] == "general_training"


def test_writing_skill_set_track_authoritative_on_usage_not_users_column():
    """Setting Writing Skill track writes usage; users.exam_module is preference-only."""
    with (
        patch(
            "app.practice.writing_skill_track.resolve_entitlements",
            return_value=_ent(writing_skill=True),
        ),
        patch(
            "app.practice.writing_skill_track.get_writing_skill_course_context",
            return_value=_ctx(exam_module=None),
        ),
        patch(
            "app.payments.repository.set_user_program_exam_module_atomic",
            return_value=_usage(exam_module="academic"),
        ) as set_usage,
        patch(
            "app.practice.writing_skill_track._sync_profile_exam_module"
        ) as sync_profile,
    ):
        # Even if the FSP profile column already said GT, Writing Skill uses usage.
        out = set_writing_skill_exam_module(user_id=USER_ID, exam_module="academic")

    assert out["exam_module"] == "academic"
    set_usage.assert_called_once()
    assert set_usage.call_args.kwargs["exam_module"] == "academic"
    sync_profile.assert_called_once_with(
        user_id=USER_ID, exam_module="academic"
    )
