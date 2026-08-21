"""Phase 2: durable Question Bank assignment ledger."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

from app.admin import question_bank as qb
from app.admin.schemas import (
    ListeningBuilderQuestionIn,
    ListeningBuilderSaveRequest,
    PatchQuestionBankSetStatusRequest,
)
from app.practice import assignment_ledger as ledger
from app.practice.schemas import SkillHubProgressOut

USER_ID = UUID("00000000-0000-0000-0000-000000000021")
ADMIN_ID = UUID("22222222-2222-4222-8222-222222222222")
SET_ID = UUID("11111111-1111-4111-8111-111111111111")
HUB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SET_STR = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LEGACY_HUB = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260818121000_user_practice_assignments.sql"
)


def _sql() -> str:
    return MIGRATION.read_text()


def _qb_hub(
    hub_id: str = HUB_ID,
    set_id: str = SET_STR,
    *,
    skill: str = "listening",
    bank_number: int = 5,
    submit_type: str = "bank",
) -> dict:
    return {
        "id": hub_id,
        "slug": f"{skill}-custom-1",
        "set_id": set_id,
        "submit_config": {"type": submit_type} if submit_type else {},
        "practice_sets": {
            "id": set_id,
            "set_number": 1,
            "status": "published",
            "practice_banks": {"skill": skill, "bank_number": bank_number},
        },
    }


def _legacy_hub() -> dict:
    return _qb_hub(LEGACY_HUB, "legacy-set", bank_number=1, submit_type="")


def _listening_body() -> ListeningBuilderSaveRequest:
    return ListeningBuilderSaveRequest(
        audio_key="bank/x/listening/part1/audio.mp3",
        instructions="Listen carefully",
        questions=[
            ListeningBuilderQuestionIn(
                question_type="Note completion",
                prompt="Name?",
                correct_answer="Ann",
                alt_answers=[],
            )
        ],
    )


def _set_row(*, status: str) -> dict:
    return {
        "id": str(SET_ID),
        "status": status,
        "practice_banks": {"skill": "listening", "bank_number": 5},
    }


def _sb_for_record(hubs: list[dict], upserts: list | None = None) -> MagicMock:
    captured = upserts if upserts is not None else []
    hub_chain = MagicMock()
    hub_chain.select.return_value = hub_chain
    hub_chain.in_.return_value = hub_chain
    hub_chain.execute.return_value = MagicMock(data=hubs)

    assign_chain = MagicMock()
    assign_chain.upsert.side_effect = lambda *a, **k: (
        captured.append({"args": a, "kwargs": k}) or assign_chain
    )
    assign_chain.execute.return_value = MagicMock(data=[])

    sb = MagicMock()

    def table(name: str):
        if name == "practice_hubs":
            return hub_chain
        if name == "user_practice_assignments":
            return assign_chain
        raise AssertionError(f"unexpected table {name}")

    sb.table.side_effect = table
    return sb


def test_ledger_table_sql_has_required_columns():
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS user_practice_assignments" in sql
    for col in (
        "user_id",
        "hub_id",
        "practice_set_id",
        "skill",
        "assigned_on",
        "source",
    ):
        assert col in sql
    for src in ("plan_generate", "publish_fill", "replan", "serve_fill"):
        assert src in sql


def test_unique_user_practice_set_constraint_in_migration():
    assert "UNIQUE (user_id, practice_set_id)" in _sql()


def test_unique_user_hub_constraint_in_migration():
    assert "UNIQUE (user_id, hub_id)" in _sql()


def test_existing_plan_assignment_creates_ledger_row():
    upserts: list = []
    sb = _sb_for_record([_qb_hub()], upserts)
    plan = {
        "prep_start": "2026-08-18",
        "assigned_hub_ids": [HUB_ID],
        "weeks": [
            {
                "days": [
                    {
                        "tasks": [
                            {"hub_id": HUB_ID, "module": "listening"},
                        ]
                    }
                ]
            }
        ],
    }
    with (
        patch("app.practice.assignment_ledger.get_supabase", return_value=sb),
        patch("app.practice.assignment_ledger._exec", side_effect=lambda q: q.execute()),
    ):
        n = ledger.record_assignments_from_study_plan(
            user_id=USER_ID,
            study_plan=plan,
            source="plan_generate",
        )
    assert n == 1
    assert upserts[0]["kwargs"]["on_conflict"] == "user_id,hub_id"
    assert upserts[0]["kwargs"]["ignore_duplicates"] is True
    row = upserts[0]["args"][0][0]
    assert row["user_id"] == str(USER_ID)
    assert row["hub_id"] == HUB_ID
    assert row["practice_set_id"] == SET_STR
    assert row["skill"] == "listening"
    assert row["source"] == "plan_generate"
    assert row["assigned_on"] == "2026-08-18"


def test_same_assignment_twice_does_not_replace_ledger_row():
    upserts: list = []
    sb = _sb_for_record([_qb_hub()], upserts)
    with (
        patch("app.practice.assignment_ledger.get_supabase", return_value=sb),
        patch("app.practice.assignment_ledger._exec", side_effect=lambda q: q.execute()),
    ):
        first = ledger.record_practice_assignments(
            user_id=USER_ID,
            hub_ids=[HUB_ID, HUB_ID],
            source="plan_generate",
            assigned_on=date(2026, 8, 1),
        )
        second = ledger.record_practice_assignments(
            user_id=USER_ID,
            hub_ids=[HUB_ID],
            source="replan",
            assigned_on=date(2026, 8, 10),
        )
    assert first == 1
    assert second == 1
    assert len(upserts) == 2
    for call in upserts:
        assert call["kwargs"]["ignore_duplicates"] is True
        assert call["kwargs"]["on_conflict"] == "user_id,hub_id"
        assert len(call["args"][0]) == 1


def test_complete_hub_progress_independent_of_ledger():
    from app.practice import service

    hub_row = _qb_hub()
    hub_row["videos"] = []
    with (
        patch("app.practice.service.repository.get_hub_by_id", return_value=hub_row),
        patch("app.practice.service.repository.is_hub_assignable", return_value=True),
        patch("app.practice.service.repository.list_hubs_for_skill", return_value=[hub_row]),
        patch("app.practice.service.repository.get_user_progress_map", return_value={}),
        patch(
            "app.practice.service.resolve_practice_skill_access",
            return_value="fsp",
        ),
        patch(
            "app.practice.catalog.get_ordered_hub_ids_by_skill",
            return_value={"listening": [HUB_ID]},
        ),
        patch(
            "app.practice.service.repository.upsert_hub_completed",
            return_value={
                "status": "completed",
                "completed_at": "2026-08-18T10:00:00+00:00",
            },
        ) as upsert_progress,
        patch("app.practice.service._skill_progress_for_access_mode") as mock_prog,
        patch("app.practice.assignment_ledger.record_practice_assignments") as rec,
    ):
        mock_prog.return_value = SkillHubProgressOut(
            skill="listening",
            completed_count=1,
            total_count=6,
            required_for_mock=6,
            mock_unlocked=False,
            mock_test_id="m1",
        )
        out = service.complete_hub(user_id=USER_ID, hub_id=HUB_ID)
    assert out.status == "completed"
    upsert_progress.assert_called_once()
    rec.assert_not_called()


def test_published_set_edit_does_not_create_ledger_row():
    with (
        patch(
            "app.admin.question_bank._load_set_skill",
            return_value=(_set_row(status="published"), "listening"),
        ),
        patch("app.admin.question_bank._upsert_section", return_value="sec-1"),
        patch("app.admin.question_bank._replace_questions"),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.admin.question_bank.get_supabase", return_value=MagicMock()),
        patch("app.practice.repository.bump_practice_catalog_version", return_value=5),
        patch("app.admin.question_bank._clear_practice_catalog_cache"),
        patch("app.practice.assignment_ledger.record_practice_assignments") as rec,
    ):
        res = qb.save_bank_listening(
            set_id=SET_ID, part=1, body=_listening_body(), admin_id=ADMIN_ID
        )
    assert res.ok is True
    rec.assert_not_called()


def test_unpublish_does_not_delete_ledger_rows():
    sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.update.return_value = chain
    chain.execute.return_value = MagicMock(data=[_set_row(status="published")])
    tables: list[str] = []

    def table(name: str):
        tables.append(name)
        return chain

    sb.table.side_effect = table
    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.practice.repository.bump_practice_catalog_version", return_value=4),
        patch("app.admin.question_bank._clear_practice_catalog_cache"),
        patch("app.practice.assignment_ledger.record_practice_assignments") as rec,
    ):
        qb.patch_question_bank_set_status(
            set_id=SET_ID,
            body=PatchQuestionBankSetStatusRequest(status="archived"),
            admin_id=ADMIN_ID,
        )
    assert "user_practice_assignments" not in tables
    rec.assert_not_called()
    assert chain.delete.call_count == 0


def test_mock_and_legacy_hubs_do_not_create_ledger_rows():
    upserts: list = []
    sb = _sb_for_record([_legacy_hub()], upserts)
    with (
        patch("app.practice.assignment_ledger.get_supabase", return_value=sb),
        patch("app.practice.assignment_ledger._exec", side_effect=lambda q: q.execute()),
    ):
        n = ledger.record_practice_assignments(
            user_id=USER_ID,
            hub_ids=[LEGACY_HUB, "missing-hub"],
            source="plan_generate",
        )
    assert n == 0
    assert upserts == []
    assert ledger.is_question_bank_hub(_qb_hub()) is True
    assert ledger.is_question_bank_hub(_legacy_hub()) is False
    assert ledger.is_question_bank_hub(None) is False


def test_backfill_from_study_plan_is_idempotent():
    upserts: list = []
    sb = _sb_for_record([_qb_hub()], upserts)
    profiles = [
        {
            "user_id": str(USER_ID),
            "study_plan": {"prep_start": "2026-08-01", "assigned_hub_ids": [HUB_ID]},
        }
    ]
    with (
        patch("app.practice.assignment_ledger.get_supabase", return_value=sb),
        patch("app.practice.assignment_ledger._exec", side_effect=lambda q: q.execute()),
    ):
        a = ledger.backfill_practice_assignments(profiles=profiles, progress_rows=[])
        b = ledger.backfill_practice_assignments(profiles=profiles, progress_rows=[])
    assert a == 1
    assert b == 1
    assert len(upserts) == 2
    assert all(c["kwargs"]["ignore_duplicates"] is True for c in upserts)
    assert "ON CONFLICT DO NOTHING" in _sql()
    assert "CREATE OR REPLACE FUNCTION backfill_user_practice_assignments" in _sql()


def test_backfill_from_progress_is_idempotent():
    upserts: list = []
    sb = _sb_for_record([_qb_hub()], upserts)
    progress = [{"user_id": str(USER_ID), "hub_id": HUB_ID}]
    with (
        patch("app.practice.assignment_ledger.get_supabase", return_value=sb),
        patch("app.practice.assignment_ledger._exec", side_effect=lambda q: q.execute()),
    ):
        a = ledger.backfill_practice_assignments(profiles=[], progress_rows=progress)
        b = ledger.backfill_practice_assignments(profiles=[], progress_rows=progress)
    assert a == 1
    assert b == 1
    assert upserts[0]["args"][0][0]["source"] == "serve_fill"
    assert all(c["kwargs"]["ignore_duplicates"] is True for c in upserts)


def test_generate_personalized_plan_records_ledger():
    from app.learning import service as learning_service

    today = date.today()
    exam = today + timedelta(days=20)
    plan_dump = {
        "prep_start": today.isoformat(),
        "assigned_hub_ids": [HUB_ID],
        "weeks": [],
        "plan_tier": "full_skill_program",
    }
    fake_plan = MagicMock()
    fake_plan.model_dump.return_value = dict(plan_dump)
    fake_plan.total_days = 21
    fake_plan.skill_difficulty = {}
    persisted = {"study_plan": plan_dump, "user_id": str(USER_ID)}

    with (
        patch(
            "app.learning.service.load_user_exam_and_target",
            return_value={"exam_date": exam.isoformat(), "target_band": 7.0},
        ),
        patch(
            "app.learning.service.load_diagnostic_seed",
            return_value={"attempt": {"id": "diag-1"}},
        ),
        patch(
            "app.learning.service.diagnostic_bands_from_attempt",
            return_value={
                "listening": 5.0,
                "reading": 5.0,
                "writing": 5.0,
                "speaking": 5.0,
            },
        ),
        patch("app.learning.service.fetch_profile_row", return_value=None),
        patch("app.learning.service.load_all_sources", return_value={}),
        patch(
            "app.learning.service.build_aggregate",
            return_value={
                "current_band": 5.0,
                "target_band": 7.0,
                "module_summary": {},
                "criterion_trends": {},
                "skill_weaknesses": [],
                "top_weaknesses": [],
                "vocab_stats": {},
                "grammar_stats": {},
                "source_counts": {},
            },
        ),
        patch("app.learning.service.build_personalized_study_plan", return_value=fake_plan),
        patch("app.learning.rules.build_recommendations", return_value=[]),
        patch("app.learning.rules.build_weekly_goals", return_value=[]),
        patch("app.learning.rules.apply_weekly_goal_completion", return_value=[]),
        patch("app.learning.service.get_supabase", return_value=MagicMock()),
        patch(
            "app.learning.service.execute_with_retry",
            return_value=MagicMock(data=[persisted]),
        ),
        patch("app.learning.service.invalidate_learning_profile_cache"),
        patch("app.learning.service.row_to_response", return_value=MagicMock()),
        patch(
            "app.practice.assignment_ledger.record_assignments_from_study_plan",
            return_value=1,
        ) as rec,
    ):
        learning_service.generate_personalized_plan(USER_ID)

    rec.assert_called_once()
    kwargs = rec.call_args.kwargs
    assert kwargs["user_id"] == USER_ID
    assert kwargs["source"] == "plan_generate"
    assert HUB_ID in kwargs["study_plan"]["assigned_hub_ids"]


def test_unique_picker_does_not_wrap():
    from app.practice.assignment import assign_hub_for_day, pick_hub_for_slot

    hubs = ["l1", "l2", "l3"]
    mapping = {"l1": "s1", "l2": "s2", "l3": "s3"}
    used_h: set[str] = set()
    used_s: set[str] = set()
    picks = [
        pick_hub_for_slot(
            skill="listening",
            hub_ids=hubs,
            hub_to_set=mapping,
            used_hub_ids=used_h,
            used_set_ids=used_s,
            day_index=i,
            completed_count=1,
        )
        for i in range(5)
    ]
    assert picks == ["l1", "l2", "l3", None, None]
    assert assign_hub_for_day(hub_ids=hubs, cursor=1, day_offset=2, used_hub_ids={"l2", "l3"}, hub_to_set=mapping) == "l1"


def test_publish_status_patch_enqueues_without_sync_fan_out():
    src = Path(qb.__file__).read_text()
    assert "apply_practice_set_status" in src
    assert "offer_published_set" not in src
    assert "list_eligible_plan_user_ids" not in src
    assert "process_catalog_changed" not in src
    assert "record_practice_assignments" not in src
    assert "publish_fill" not in src
    assert "user_learning_profiles" not in src
