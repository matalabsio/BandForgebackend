"""Phase 4: publish → practice.catalog_changed fan-out."""

from __future__ import annotations

import copy
import inspect
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.admin import question_bank as qb
from app.admin.schemas import (
    ListeningBuilderQuestionIn,
    ListeningBuilderSaveRequest,
    PatchQuestionBankSetStatusRequest,
)
from app.practice import catalog_jobs as jobs

SET_ID = UUID("11111111-1111-4111-8111-111111111111")
ADMIN_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_A = UUID("00000000-0000-0000-0000-0000000000aa")
USER_B = UUID("00000000-0000-0000-0000-0000000000bb")
TODAY = date(2026, 8, 18)
EXAM = date(2026, 12, 1)
HUB_S5 = "hub-s5"
SET_S5 = "set-s5"
HUB_S6 = "hub-s6"
SET_S6 = "set-s6"


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


def _listening_days(*, start: date, n: int, hubs: list[str | None]) -> dict:
    days = []
    for i in range(n):
        hid = hubs[i] if i < len(hubs) else None
        days.append(
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "label": "D",
                "tasks": [
                    {
                        "id": f"w-{i}",
                        "module": "listening",
                        "task_type": "watch",
                        "hub_id": hid,
                        "status": "pending",
                    },
                    {
                        "id": f"p-{i}",
                        "module": "listening",
                        "task_type": "practice",
                        "hub_id": hid,
                        "status": "pending",
                    },
                    {
                        "id": f"r-{i}",
                        "module": "reading",
                        "task_type": "practice",
                        "hub_id": "hub-reading-keep",
                        "status": "pending",
                    },
                ],
            }
        )
    return {
        "prep_start": start.isoformat(),
        "exam_date": EXAM.isoformat(),
        "plan_tier": "full_skill_program",
        "assigned_hub_ids": [h for h in hubs if h],
        "weeks": [{"id": "w1", "label": "W1", "focus": "x", "days": days}],
    }


def _listening_hubs(plan: dict) -> list[str | None]:
    out: list[str | None] = []
    for week in plan.get("weeks") or []:
        for day in week.get("days") or []:
            watches = [
                t
                for t in (day.get("tasks") or [])
                if t.get("module") == "listening" and t.get("task_type") == "watch"
            ]
            if not watches:
                continue
            hid = watches[0].get("hub_id")
            out.append(hid if hid else None)
    return out


def _profile(user_id: UUID, plan: dict, *, updated_at: str = "t0") -> dict:
    return {
        "user_id": str(user_id),
        "plan_tier": "full_skill_program",
        "exam_date": EXAM.isoformat(),
        "study_plan": copy.deepcopy(plan),
        "updated_at": updated_at,
    }


class _PlanStore:
    def __init__(self, profiles: dict[str, dict]):
        self.profiles = {uid: copy.deepcopy(row) for uid, row in profiles.items()}
        self.claims: dict[tuple[str, str], str] = {}
        self.hubs: dict[tuple[str, str], str] = {}
        self.persist_calls = 0
        self.claim_calls = 0
        self.invalidate_ids: list[str] = []
        self.cas_fail_on: set[int] = set()
        self._lock = __import__("threading").Lock()

    def fetch(self, user_id: UUID) -> dict:
        with self._lock:
            return copy.deepcopy(self.profiles[str(user_id)])

    def persist(self, *, user_id, study_plan, expected_updated_at) -> bool:
        with self._lock:
            self.persist_calls += 1
            if self.persist_calls in self.cas_fail_on:
                return False
            row = self.profiles[str(user_id)]
            if expected_updated_at and row.get("updated_at") != expected_updated_at:
                return False
            row["study_plan"] = copy.deepcopy(study_plan)
            row["updated_at"] = f"t{self.persist_calls}"
            return True

    def claim(self, *, user_id, hub_id, practice_set_id, **_kwargs) -> str:
        with self._lock:
            self.claim_calls += 1
            uid = str(user_id)
            set_key = (uid, str(practice_set_id))
            hub_key = (uid, str(hub_id))
            if set_key in self.claims:
                return "already" if self.claims[set_key] == str(hub_id) else "conflict"
            if hub_key in self.hubs:
                return (
                    "already"
                    if self.hubs[hub_key] == str(practice_set_id)
                    else "conflict"
                )
            self.claims[set_key] = str(hub_id)
            self.hubs[hub_key] = str(practice_set_id)
            return "claimed"

    def invalidate(self, user_id) -> None:
        self.invalidate_ids.append(str(user_id))


@contextmanager
def _patched_store(store: _PlanStore, *, progress: dict | None = None):
    with (
        patch(
            "app.practice.catalog_jobs.fetch_profile_row",
            side_effect=store.fetch,
        ),
        patch(
            "app.practice.catalog_jobs.get_user_progress_map",
            return_value=progress or {},
        ),
        patch(
            "app.practice.catalog_jobs.try_claim_practice_assignment",
            side_effect=store.claim,
        ),
        patch(
            "app.practice.catalog_jobs._persist_plan",
            side_effect=store.persist,
        ),
        patch(
            "app.practice.catalog_jobs.invalidate_learning_profile_cache",
            side_effect=store.invalidate,
        ),
    ):
        yield store


def _payload(*, set_id=SET_S5, hub_id=HUB_S5, skill="listening", reason="published"):
    return {
        "practice_set_id": set_id,
        "hub_id": hub_id,
        "skill": skill,
        "reason": reason,
    }


def _publish_sb(*, status: str = "draft", rpc_data: dict | None = None) -> MagicMock:
    sb = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.update.return_value = chain
    chain.execute.return_value = MagicMock(data=[_set_row(status=status)])
    sb.table.return_value = chain
    sb.rpc.return_value.execute.return_value = MagicMock(
        data=rpc_data
        if rpc_data is not None
        else {
            "prev": status,
            "status": "published",
            "job_id": "job-1",
            "hub_id": HUB_S5,
        }
    )
    return sb


def test_publish_successful_enqueues_catalog_changed():
    sb = _publish_sb()
    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch("app.admin.question_bank.bank_publish_blockers", return_value=[]),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.practice.repository.bump_practice_catalog_version", return_value=3),
        patch("app.admin.question_bank._clear_practice_catalog_cache"),
        patch("app.practice.catalog_jobs.process_catalog_changed") as fanout,
        patch("app.practice.catalog_jobs.list_eligible_plan_user_ids") as listed,
        patch("app.practice.catalog_jobs.offer_published_set") as offered,
    ):
        qb.patch_question_bank_set_status(
            set_id=SET_ID,
            body=PatchQuestionBankSetStatusRequest(status="published"),
            admin_id=ADMIN_ID,
        )
    sb.rpc.assert_called_once_with(
        "apply_practice_set_status",
        {"p_set_id": str(SET_ID), "p_status": "published"},
    )
    fanout.assert_not_called()
    listed.assert_not_called()
    offered.assert_not_called()


def test_blocked_publish_does_not_enqueue():
    sb = _publish_sb()
    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch(
            "app.admin.question_bank.bank_publish_blockers",
            return_value=["Listening: add at least one question before publishing."],
        ),
        patch("app.practice.catalog_jobs.process_catalog_changed") as fanout,
    ):
        with pytest.raises(HTTPException) as exc:
            qb.patch_question_bank_set_status(
                set_id=SET_ID,
                body=PatchQuestionBankSetStatusRequest(status="published"),
                admin_id=ADMIN_ID,
            )
    assert exc.value.status_code == 400
    sb.rpc.assert_not_called()
    fanout.assert_not_called()


def test_draft_save_does_not_enqueue():
    sb = MagicMock()
    with (
        patch(
            "app.admin.question_bank._load_set_skill",
            return_value=(_set_row(status="draft"), "listening"),
        ),
        patch("app.admin.question_bank._upsert_section", return_value="sec-1"),
        patch("app.admin.question_bank._replace_questions"),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch("app.practice.repository.bump_practice_catalog_version") as bump,
        patch("app.admin.question_bank._clear_practice_catalog_cache"),
    ):
        res = qb.save_bank_listening(
            set_id=SET_ID, part=1, body=_listening_body(), admin_id=ADMIN_ID
        )
    assert res.ok is True
    bump.assert_not_called()
    rpc_names = [c.args[0] for c in sb.rpc.call_args_list if c.args]
    assert "apply_practice_set_status" not in rpc_names
    assert "enqueue_practice_catalog_changed" not in rpc_names


def test_published_set_content_edit_does_not_enqueue_assignment():
    sb = MagicMock()
    with (
        patch(
            "app.admin.question_bank._load_set_skill",
            return_value=(_set_row(status="published"), "listening"),
        ),
        patch("app.admin.question_bank._upsert_section", return_value="sec-1"),
        patch("app.admin.question_bank._replace_questions"),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch(
            "app.practice.repository.bump_practice_catalog_version",
            return_value=5,
        ) as bump,
        patch("app.admin.question_bank._clear_practice_catalog_cache"),
        patch("app.practice.catalog_jobs.offer_published_set") as offered,
    ):
        res = qb.save_bank_listening(
            set_id=SET_ID, part=1, body=_listening_body(), admin_id=ADMIN_ID
        )
    assert res.ok is True
    bump.assert_called_once()
    offered.assert_not_called()
    rpc_names = [c.args[0] for c in sb.rpc.call_args_list if c.args]
    assert "apply_practice_set_status" not in rpc_names
    assert "enqueue_practice_catalog_changed" not in rpc_names


def test_one_user_empty_capacity_assigns_s5_once():
    plan = _listening_days(
        start=TODAY, n=10, hubs=["S1", "S2", "S3", "S4"] + [None] * 6
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        stats = jobs.process_catalog_changed(
            _payload(),
            user_ids=[str(USER_A)],
            today=TODAY,
            set_is_published=True,
        )
    assert stats["users_filled"] == 1
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[:4] == ["S1", "S2", "S3", "S4"]
    assert hubs[4] == HUB_S5
    assert hubs[5:] == [None] * 5
    assert store.claim_calls == 1
    assert SET_S5 in {k[1] for k in store.claims}
    assert store.invalidate_ids == [str(USER_A)]


def test_user_with_no_capacity_gets_nothing():
    plan = _listening_days(start=TODAY, n=4, hubs=["S1", "S2", "S3", "S4"])
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        stats = jobs.process_catalog_changed(
            _payload(),
            user_ids=[str(USER_A)],
            today=TODAY,
            set_is_published=True,
        )
    assert stats["users_no_capacity"] == 1
    assert stats["users_filled"] == 0
    assert store.claim_calls == 0
    assert _listening_hubs(store.profiles[str(USER_A)]["study_plan"]) == [
        "S1",
        "S2",
        "S3",
        "S4",
    ]


def test_user_already_has_s5_no_duplicate():
    plan = _listening_days(
        start=TODAY, n=6, hubs=["S1", "S2", "S3", "S4", HUB_S5, None]
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    store.claims[(str(USER_A), SET_S5)] = HUB_S5
    store.hubs[(str(USER_A), HUB_S5)] = SET_S5
    with _patched_store(store):
        first = jobs.process_catalog_changed(
            _payload(),
            user_ids=[str(USER_A)],
            today=TODAY,
            set_is_published=True,
        )
        second = jobs.process_catalog_changed(
            _payload(),
            user_ids=[str(USER_A)],
            today=TODAY,
            set_is_published=True,
        )
    assert first["users_already_had_set"] == 1
    assert second["users_already_had_set"] == 1
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs.count(HUB_S5) == 1
    assert hubs[5] is None
    assert len(store.claims) == 1


def test_plan_has_s5_ledger_missing_no_duplicate():
    plan = _listening_days(
        start=TODAY, n=6, hubs=["S1", "S2", "S3", "S4", HUB_S5, None]
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        stats = jobs.process_catalog_changed(
            _payload(),
            user_ids=[str(USER_A)],
            today=TODAY,
            set_is_published=True,
        )
    assert stats["users_already_had_set"] == 1
    assert _listening_hubs(store.profiles[str(USER_A)]["study_plan"]).count(HUB_S5) == 1
    assert store.persist_calls == 0
    assert store.claims[(str(USER_A), SET_S5)] == HUB_S5


def test_two_users_can_both_receive_s5():
    plan = _listening_days(
        start=TODAY, n=6, hubs=["S1", "S2", "S3", "S4", None, None]
    )
    store = _PlanStore(
        {
            str(USER_A): _profile(USER_A, plan),
            str(USER_B): _profile(USER_B, plan),
        }
    )
    with _patched_store(store):
        stats = jobs.process_catalog_changed(
            _payload(),
            user_ids=[str(USER_A), str(USER_B)],
            today=TODAY,
            set_is_published=True,
        )
    assert stats["users_filled"] == 2
    assert _listening_hubs(store.profiles[str(USER_A)]["study_plan"])[4] == HUB_S5
    assert _listening_hubs(store.profiles[str(USER_B)]["study_plan"])[4] == HUB_S5


def test_four_old_sets_ten_days_publish_s5_fills_one_empty():
    plan = _listening_days(
        start=TODAY, n=10, hubs=["S1", "S2", "S3", "S4"] + [None] * 6
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[:4] == ["S1", "S2", "S3", "S4"]
    assert hubs.count(HUB_S5) == 1
    assert sum(1 for h in hubs if h is None) == 5
    reading = [
        t.get("hub_id")
        for t in store.profiles[str(USER_A)]["study_plan"]["weeks"][0]["days"][0]["tasks"]
        if t.get("module") == "reading"
    ]
    assert reading == ["hub-reading-keep"]


def test_publish_s5_then_s6_fills_two_empty_days():
    plan = _listening_days(
        start=TODAY, n=10, hubs=["S1", "S2", "S3", "S4"] + [None] * 6
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S6,
            hub_id=HUB_S6,
            skill="listening",
            today=TODAY,
        )
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[:4] == ["S1", "S2", "S3", "S4"]
    assert hubs[4] == HUB_S5
    assert hubs[5] == HUB_S6
    assert hubs[6:] == [None] * 4


def test_retry_same_s5_event_is_idempotent():
    plan = _listening_days(
        start=TODAY, n=10, hubs=["S1", "S2", "S3", "S4"] + [None] * 6
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        a = jobs.process_catalog_changed(
            _payload(),
            user_ids=[str(USER_A)],
            today=TODAY,
            set_is_published=True,
        )
        b = jobs.process_catalog_changed(
            _payload(),
            user_ids=[str(USER_A)],
            today=TODAY,
            set_is_published=True,
        )
    assert a["users_filled"] == 1
    assert b["users_filled"] == 0
    assert b["users_already_had_set"] == 1
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[4] == HUB_S5
    assert hubs.count(HUB_S5) == 1
    assert HUB_S6 not in hubs


def test_worker_crash_after_claim_retry_does_not_duplicate():
    plan = _listening_days(
        start=TODAY, n=6, hubs=["S1", "S2", "S3", "S4", None, None]
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    store.cas_fail_on = {1, 2, 3}
    with _patched_store(store):
        first = jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
            persist_attempts=3,
        )
        assert first == "failed"
        assert len(store.claims) == 1
        store.cas_fail_on = set()
        second = jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    assert second == "filled"
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs.count(HUB_S5) == 1
    assert len(store.claims) == 1


def test_concurrent_s5_s6_does_not_overwrite():
    plan = _listening_days(
        start=TODAY, n=10, hubs=["S1", "S2", "S3", "S4"] + [None] * 6
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    store.cas_fail_on = {2}
    with _patched_store(store):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S6,
            hub_id=HUB_S6,
            skill="listening",
            today=TODAY,
        )
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[:4] == ["S1", "S2", "S3", "S4"]
    assert set(hubs[4:6]) == {HUB_S5, HUB_S6}
    assert hubs.count(HUB_S5) == 1
    assert hubs.count(HUB_S6) == 1


def test_today_started_is_not_replaced():
    plan = _listening_days(
        start=TODAY, n=4, hubs=["S1", None, None, None]
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    progress = {"S1": {"status": "in_progress"}}
    with (
        patch("app.practice.catalog_jobs.fetch_profile_row", side_effect=store.fetch),
        patch("app.practice.catalog_jobs.get_user_progress_map", return_value=progress),
        patch("app.practice.catalog_jobs.try_claim_practice_assignment", side_effect=store.claim),
        patch("app.practice.catalog_jobs._persist_plan", side_effect=store.persist),
        patch("app.practice.catalog_jobs.invalidate_learning_profile_cache", side_effect=store.invalidate),
    ):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[0] == "S1"
    assert hubs[1] == HUB_S5


def test_future_assigned_is_not_replaced():
    plan = _listening_days(
        start=TODAY, n=4, hubs=["S1", "S2", None, None]
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[1] == "S2"
    assert hubs[2] == HUB_S5


def test_past_is_not_replaced():
    start = TODAY - timedelta(days=2)
    plan = _listening_days(start=start, n=4, hubs=[None, "S1", None, None])
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[0] is None
    assert hubs[1] == "S1"
    assert hubs[2] == HUB_S5


def test_unpublish_skips_new_assignment_keeps_existing():
    plan = _listening_days(
        start=TODAY, n=6, hubs=["S1", "S2", "S3", "S4", HUB_S5, None]
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    offered = MagicMock(return_value="filled")
    stats = jobs.process_catalog_changed(
        _payload(),
        user_ids=[str(USER_A)],
        today=TODAY,
        offer=offered,
        set_is_published=False,
    )
    assert stats.get("skipped") is True
    offered.assert_not_called()
    assert _listening_hubs(store.profiles[str(USER_A)]["study_plan"])[4] == HUB_S5


def test_unpublish_status_patch_does_not_delete_ledger_or_enqueue_assignment():
    sb = _publish_sb(status="published", rpc_data={"prev": "published", "status": "archived", "job_id": None})
    tables: list[str] = []

    def table(name: str):
        tables.append(name)
        return sb.table.return_value

    sb.table.side_effect = table
    with (
        patch("app.admin.question_bank.get_supabase", return_value=sb),
        patch("app.admin.question_bank.refresh_hub_submit_configs"),
        patch("app.admin.question_bank.log_admin_action"),
        patch("app.practice.repository.bump_practice_catalog_version", return_value=4),
        patch("app.admin.question_bank._clear_practice_catalog_cache"),
        patch("app.practice.catalog_jobs.offer_published_set") as offered,
    ):
        qb.patch_question_bank_set_status(
            set_id=SET_ID,
            body=PatchQuestionBankSetStatusRequest(status="archived"),
            admin_id=ADMIN_ID,
        )
    sb.rpc.assert_called_once_with(
        "apply_practice_set_status",
        {"p_set_id": str(SET_ID), "p_status": "archived"},
    )
    offered.assert_not_called()
    assert "user_practice_assignments" not in tables


def test_mock_content_paths_do_not_assign_ledger():
    from app.admin import listening_builder, reading_builder, speaking_builder

    for mod in (listening_builder, reading_builder, speaking_builder):
        src = inspect.getsource(mod)
        assert "apply_practice_set_status" not in src
        assert "catalog_changed" not in src
        assert "user_practice_assignments" not in src
    src = inspect.getsource(jobs)
    assert "from app.admin" not in src
    assert 'table("questions")' not in src


def test_pagination_processes_more_users_than_one_batch():
    users = [f"user-{i:03d}" for i in range(5)]
    pages: list[list[str]] = []

    def list_users(*, after_user_id=None, limit=2):
        start = 0
        if after_user_id:
            start = users.index(after_user_id) + 1
        batch = users[start : start + limit]
        pages.append(batch)
        return batch

    outcomes = {uid: "filled" for uid in users}

    def offer(**kwargs):
        return outcomes[str(kwargs["user_id"])]

    stats = jobs.process_catalog_changed(
        _payload(),
        user_batch_size=2,
        list_users=list_users,
        offer=offer,
        set_is_published=True,
        today=TODAY,
    )
    assert stats["users_scanned"] == 5
    assert stats["users_filled"] == 5
    assert len(pages) >= 3
    assert [len(p) for p in pages if p] == [2, 2, 1]


def test_one_user_failure_does_not_abort_others():
    seen: list[str] = []

    def offer(**kwargs):
        uid = str(kwargs["user_id"])
        seen.append(uid)
        if uid == "u2":
            raise RuntimeError("boom")
        return "filled"

    stats = jobs.process_catalog_changed(
        _payload(),
        user_ids=["u1", "u2", "u3"],
        offer=offer,
        set_is_published=True,
        today=TODAY,
    )
    assert seen == ["u1", "u2", "u3"]
    assert stats["users_filled"] == 2
    assert stats["persistence_failures"] == 1


def test_publish_endpoint_does_not_synchronously_iterate_users():
    src = inspect.getsource(qb.patch_question_bank_set_status)
    assert "list_eligible_plan_user_ids" not in src
    assert "offer_published_set" not in src
    assert "process_catalog_changed" not in src
    assert "user_learning_profiles" not in src
    assert "apply_practice_set_status" in src


def test_job_retry_marks_retry_when_user_persist_fails():
    row = {
        "id": "job-1",
        "lease_token": "tok",
        "attempts": 1,
        "max_attempts": 8,
        "payload": _payload(),
    }
    with (
        patch(
            "app.practice.catalog_jobs.process_catalog_changed",
            return_value={"persistence_failures": 2, "users_filled": 1},
        ),
        patch("app.practice.catalog_jobs.mark_job_retry") as retry,
        patch("app.practice.catalog_jobs.mark_job_done") as done,
    ):
        jobs.process_job_row(row)
    retry.assert_called_once()
    done.assert_not_called()


def test_s5_event_never_calls_generic_picker():
    plan = _listening_days(
        start=TODAY, n=6, hubs=["S1", "S2", "S3", "S4", None, None]
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with (
        _patched_store(store),
        patch("app.practice.assignment.pick_unused_hub") as pick,
        patch("app.practice.assignment.pick_hub_for_slot") as slot,
    ):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    pick.assert_not_called()
    slot.assert_not_called()
    assert _listening_hubs(store.profiles[str(USER_A)]["study_plan"])[4] == HUB_S5


def test_ineligible_user_is_skipped():
    plan = _listening_days(start=TODAY, n=4, hubs=[None] * 4)
    plan["plan_tier"] = "diagnostic"
    plan["exam_date"] = "2020-01-01"
    row = {
        "user_id": str(USER_A),
        "plan_tier": "diagnostic",
        "exam_date": "2020-01-01",
        "study_plan": plan,
        "updated_at": "t0",
    }
    store = _PlanStore({str(USER_A): row})
    with _patched_store(store):
        out = jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    assert out == "ineligible"
    assert store.claim_calls == 0


def test_find_eligible_empty_day_prefers_earliest_future():
    plan = _listening_days(
        start=TODAY, n=5, hubs=["S1", None, "S3", None, None]
    )
    day = jobs.find_eligible_empty_day(plan, skill="listening", today=TODAY)
    assert day is not None
    assert day["date"] == (TODAY + timedelta(days=1)).isoformat()
