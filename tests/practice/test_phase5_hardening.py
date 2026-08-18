"""Phase 5: concurrency, recovery, jobs, pagination, eligibility, sticky calendar."""

from __future__ import annotations

import copy
import inspect
import threading
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.admin import question_bank as qb
from app.learning import service as learning_service
from app.practice import assignment as assignment_mod
from app.practice import catalog_jobs as jobs
from app.practice.assignment import rewrite_plan_hubs
from app.practice.invariants import (
    cross_skill_mutation_issues,
    same_day_stack_issues,
)

from tests.practice.test_catalog_changed import (
    EXAM,
    HUB_S5,
    HUB_S6,
    SET_S5,
    SET_S6,
    TODAY,
    USER_A,
    USER_B,
    _PlanStore,
    _listening_days,
    _listening_hubs,
    _payload,
    _patched_store,
    _profile,
)

MIGRATION_JOBS = (
    Path(__file__).resolve().parents[2]
    / "supabase/migrations/20260818122000_practice_catalog_jobs.sql"
)
MIGRATION_LEDGER = (
    Path(__file__).resolve().parents[2]
    / "supabase/migrations/20260818121000_user_practice_assignments.sql"
)


def test_ledger_unique_constraints_remain():
    sql = MIGRATION_LEDGER.read_text()
    assert "UNIQUE (user_id, practice_set_id)" in sql
    assert "UNIQUE (user_id, hub_id)" in sql


def test_no_assignment_path_bypasses_claim_helpers():
    src_assign = Path(assignment_mod.__file__).read_text()
    src_jobs = Path(jobs.__file__).read_text()
    src_rules = Path(
        Path(__file__).resolve().parents[2] / "app/learning/rules.py"
    ).read_text()
    assert "try_claim_practice_assignment" in src_assign or "_claim_candidate" in src_assign
    assert "try_claim_practice_assignment" in src_jobs
    assert "claim=bool(claim_assignments and user_id)" in src_rules
    gen = inspect.getsource(learning_service.generate_personalized_plan)
    assert "claim_assignments=True" in gen


def test_crash_recovery_places_ledger_orphan_not_next_catalog_set():
    plan = _listening_days(
        start=TODAY, n=6, hubs=["S1", "S2", "S3", "S4", None, None]
    )
    with patch(
        "app.practice.assignment_ledger.list_user_assignment_ids",
        return_value=({HUB_S5}, {SET_S5}),
    ):
        out = rewrite_plan_hubs(
            plan,
            ordered_ids={
                "listening": ["S1", "S2", "S3", "S4", HUB_S5, HUB_S6],
                "reading": [],
                "writing": [],
                "speaking": [],
            },
            hub_to_set={
                "S1": "set-s1",
                "S2": "set-s2",
                "S3": "set-s3",
                "S4": "set-s4",
                HUB_S5: SET_S5,
                HUB_S6: SET_S6,
            },
            today=TODAY,
            user_id=USER_A,
            claim=False,
        )
    hubs = _listening_hubs(out)
    assert hubs[:4] == ["S1", "S2", "S3", "S4"]
    assert hubs[4] == HUB_S5
    assert hubs.count(HUB_S5) == 1


def test_unpublished_orphan_is_not_placed():
    plan = _listening_days(start=TODAY, n=3, hubs=["S1", None, None])
    with patch(
        "app.practice.assignment_ledger.list_user_assignment_ids",
        return_value=({HUB_S5}, {SET_S5}),
    ):
        out = rewrite_plan_hubs(
            plan,
            ordered_ids={
                "listening": ["S1", HUB_S6],
                "reading": [],
                "writing": [],
                "speaking": [],
            },
            hub_to_set={"S1": "set-s1", HUB_S5: SET_S5, HUB_S6: SET_S6},
            today=TODAY,
            user_id=USER_A,
            claim=False,
        )
    hubs = _listening_hubs(out)
    assert HUB_S5 not in hubs
    assert hubs[1] == HUB_S6


def test_two_simultaneous_s5_events_assign_once():
    plan = _listening_days(
        start=TODAY, n=6, hubs=["S1", "S2", "S3", "S4", None, None]
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    lock = threading.Lock()
    orig_claim = store.claim

    def slow_claim(**kwargs):
        with lock:
            return orig_claim(**kwargs)

    store.claim = slow_claim
    results: list[str] = []

    def run():
        with _patched_store(store):
            results.append(
                jobs.offer_published_set(
                    user_id=USER_A,
                    practice_set_id=SET_S5,
                    hub_id=HUB_S5,
                    skill="listening",
                    today=TODAY,
                )
            )

    t1 = threading.Thread(target=run)
    t2 = threading.Thread(target=run)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert sorted(results) in (
        ["already_had_set", "filled"],
        ["filled", "already_had_set"],
        ["filled", "filled"],
    )
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs.count(HUB_S5) == 1
    assert len(store.claims) == 1


def test_concurrent_s5_s6_two_empty_days():
    plan = _listening_days(
        start=TODAY, n=10, hubs=["S1", "S2", "S3", "S4"] + [None] * 6
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    results: dict[str, str] = {}

    def run(set_id: str, hub: str):
        with _patched_store(store):
            results[set_id] = jobs.offer_published_set(
                user_id=USER_A,
                practice_set_id=set_id,
                hub_id=hub,
                skill="listening",
                today=TODAY,
            )

    t1 = threading.Thread(target=run, args=(SET_S5, HUB_S5))
    t2 = threading.Thread(target=run, args=(SET_S6, HUB_S6))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[:4] == ["S1", "S2", "S3", "S4"]
    assigned = {h for h in hubs[4:] if h}
    assert assigned <= {HUB_S5, HUB_S6}
    assert HUB_S5 not in hubs[:4]
    assert len(store.claims) == len(assigned)


def test_cas_loser_does_not_overwrite_winner_assignment():
    plan_a = _listening_days(
        start=TODAY, n=6, hubs=["S1", "S2", "S3", "S4", None, None]
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan_a)})
    with _patched_store(store):
        assert (
            jobs.offer_published_set(
                user_id=USER_A,
                practice_set_id=SET_S5,
                hub_id=HUB_S5,
                skill="listening",
                today=TODAY,
            )
            == "filled"
        )
        stale_expected = "t0"
        mutated = copy.deepcopy(store.profiles[str(USER_A)]["study_plan"])
        jobs._apply_hub_to_day(mutated["weeks"][0]["days"][5], skill="listening", hub_id=HUB_S6)
        ok = jobs._persist_plan(
            user_id=USER_A,
            study_plan=mutated,
            expected_updated_at=stale_expected,
        )
    assert ok is False
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[4] == HUB_S5
    assert HUB_S6 not in hubs


def test_serve_fill_persist_uses_cas_eq_updated_at():
    src = inspect.getsource(learning_service._persist_filled_study_plan)
    assert "expected_updated_at" in src
    assert '.eq("updated_at"' in src or "eq(\"updated_at\"" in src


def test_historical_calendar_publish_s4_then_s5_after_complete():
    start = TODAY
    plan = _listening_days(
        start=start, n=5, hubs=["S1", "S2", "S3", None, None]
    )
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id="set-s4",
            hub_id="S4",
            skill="listening",
            today=TODAY,
        )
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs == ["S1", "S2", "S3", "S4", None]
    with _patched_store(store, progress={"S1": {"status": "completed"}}):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id="set-s5",
            hub_id="S5",
            skill="listening",
            today=TODAY,
        )
    hubs = _listening_hubs(store.profiles[str(USER_A)]["study_plan"])
    assert hubs[0] == "S1"
    assert hubs[3] == "S4"
    assert hubs[4] == "S5"


def test_same_day_stack_after_publish_fill():
    plan = _listening_days(start=TODAY, n=3, hubs=["S1", None, None])
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    filled = store.profiles[str(USER_A)]["study_plan"]
    assert same_day_stack_issues(user_id=str(USER_A), study_plan=filled) == []
    day = filled["weeks"][0]["days"][1]
    listening = [t["hub_id"] for t in day["tasks"] if t["module"] == "listening"]
    assert listening == [HUB_S5] * 2


def test_listening_publish_does_not_touch_other_skills():
    plan = _listening_days(start=TODAY, n=4, hubs=["S1", "S2", None, None])
    before = copy.deepcopy(plan)
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    after = store.profiles[str(USER_A)]["study_plan"]
    assert (
        cross_skill_mutation_issues(
            user_id=str(USER_A),
            before=before,
            after=after,
            target_skill="listening",
        )
        == []
    )


def test_pagination_exact_and_short_batches():
    users = [f"u{i:02d}" for i in range(4)]

    def list_users(*, after_user_id=None, limit=2):
        start = 0
        if after_user_id:
            start = users.index(after_user_id) + 1
        return users[start : start + limit]

    seen: list[str] = []

    def offer(**kwargs):
        seen.append(str(kwargs["user_id"]))
        return "filled"

    stats = jobs.process_catalog_changed(
        _payload(),
        user_batch_size=2,
        list_users=list_users,
        offer=offer,
        set_is_published=True,
        today=TODAY,
    )
    assert seen == users
    assert stats["users_scanned"] == 4

    seen.clear()
    stats = jobs.process_catalog_changed(
        _payload(),
        user_batch_size=10,
        list_users=list_users,
        offer=offer,
        set_is_published=True,
        today=TODAY,
    )
    assert seen == users
    assert stats["users_scanned"] == 4


def test_pagination_does_not_skip_users_after_cursor():
    users = ["a", "b", "c", "d"]
    inserted = {"done": False}

    def list_users(*, after_user_id=None, limit=2):
        live = list(users)
        if after_user_id == "b" and not inserted["done"]:
            live.insert(2, "b-new")
            inserted["done"] = True
        start = 0
        if after_user_id:
            start = live.index(after_user_id) + 1
        return live[start : start + limit]

    seen: list[str] = []

    def offer(**kwargs):
        seen.append(str(kwargs["user_id"]))
        return "no_capacity"

    jobs.process_catalog_changed(
        _payload(),
        user_batch_size=2,
        list_users=list_users,
        offer=offer,
        set_is_published=True,
        today=TODAY,
    )
    assert "a" in seen and "b" in seen
    assert "b-new" in seen
    assert "c" in seen and "d" in seen


def test_user_ineligible_between_pages_is_counted_not_filled():
    def offer(**kwargs):
        if str(kwargs["user_id"]) == "u2":
            return "ineligible"
        return "filled"

    stats = jobs.process_catalog_changed(
        _payload(),
        user_ids=["u1", "u2", "u3"],
        offer=offer,
        set_is_published=True,
        today=TODAY,
    )
    assert stats["users_filled"] == 2
    assert stats["users_ineligible"] == 1


def test_eligibility_sql_matches_existing_semantics():
    sql = MIGRATION_JOBS.read_text()
    assert "plan_tier = 'full_skill_program'" in sql
    assert "p.slug = 'full_skill_program'" in sql
    assert "s.status = 'active'" in sql
    assert "s.expires_at > now()" in sql
    assert "CURRENT_DATE" in sql
    assert "study_plan <> '{}'::jsonb" in sql


def test_job_sql_has_lease_skip_locked_and_idempotency():
    sql = MIGRATION_JOBS.read_text()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "idempotency_key" in sql
    assert "ON CONFLICT (idempotency_key)" in sql
    assert "'done', 'failed'" in sql


def test_job_max_attempts_marks_failed():
    row = {
        "id": "job-1",
        "lease_token": "tok",
        "attempts": 8,
        "max_attempts": 8,
        "payload": _payload(),
    }
    captured: dict = {}

    def leased(job_row, values):
        captured.update(values)
        return True

    with patch("app.practice.catalog_jobs._leased_update", side_effect=leased):
        jobs.mark_job_retry(row, error="persistence_failures=1", result={})
    assert captured["status"] == "failed"


def test_job_retry_backoff_before_max_attempts():
    row = {
        "id": "job-1",
        "lease_token": "tok",
        "attempts": 2,
        "max_attempts": 8,
    }
    captured: dict = {}

    def leased(job_row, values):
        captured.update(values)
        return True

    with patch("app.practice.catalog_jobs._leased_update", side_effect=leased):
        jobs.mark_job_retry(row, error="err", result=None)
    assert captured["status"] == "retry"
    assert captured["next_attempt_at"]


def test_unexpected_worker_error_is_not_marked_done():
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
            side_effect=RuntimeError("db"),
        ),
        patch("app.practice.catalog_jobs.mark_job_retry") as retry,
        patch("app.practice.catalog_jobs.mark_job_done") as done,
    ):
        with pytest.raises(RuntimeError):
            jobs.process_job_row(row)
    retry.assert_called_once()
    done.assert_not_called()


def test_duplicate_enqueue_and_done_job_sql_revive():
    sql = MIGRATION_JOBS.read_text()
    assert "WHEN practice_jobs.status IN ('done', 'failed') THEN 'queued'" in sql


def test_invalid_hub_skips_without_offering():
    offered = MagicMock(return_value="filled")
    stats = jobs.process_catalog_changed(
        _payload(),
        user_ids=[str(USER_A)],
        offer=offered,
        set_is_published=True,
        hub_matches_set=False,
        today=TODAY,
    )
    assert stats.get("skipped") is True
    assert stats.get("skip_reason") == "invalid_hub"
    offered.assert_not_called()


def test_worker_healthcheck_does_not_claim():
    info = jobs.healthcheck(ping=False)
    assert info["ok"] is True
    assert info["job_type"] == "practice.catalog_changed"
    src = inspect.getsource(jobs.healthcheck)
    assert "claim_practice_jobs" not in src


def test_worker_script_and_entrypoint_exist():
    script = (
        Path(__file__).resolve().parents[2] / "scripts/run_practice_job_worker.sh"
    )
    text = script.read_text()
    assert "python -m app.practice.catalog_jobs" in text
    assert inspect.getsource(jobs.main)
    assert "PRACTICE_JOB_USER_BATCH_SIZE" in Path(
        Path(__file__).resolve().parents[2] / "app/config.py"
    ).read_text()


def test_question_bank_never_writes_questions_table():
    src = Path(qb.__file__).read_text()
    assert 'table("questions")' not in src


def test_pool_exhausted_stays_unavailable():
    plan = _listening_days(start=TODAY, n=4, hubs=["S1", "S2", "S3", "S4"])
    store = _PlanStore({str(USER_A): _profile(USER_A, plan)})
    with _patched_store(store):
        out = jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    assert out == "no_capacity"
    assert store.claim_calls == 0
    assert _listening_hubs(store.profiles[str(USER_A)]["study_plan"]) == [
        "S1",
        "S2",
        "S3",
        "S4",
    ]


def test_two_users_may_share_s5():
    plan = _listening_days(start=TODAY, n=5, hubs=["S1", None, None, None, None])
    store = _PlanStore(
        {
            str(USER_A): _profile(USER_A, plan),
            str(USER_B): _profile(USER_B, plan),
        }
    )
    with _patched_store(store):
        a = jobs.offer_published_set(
            user_id=USER_A,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
        b = jobs.offer_published_set(
            user_id=USER_B,
            practice_set_id=SET_S5,
            hub_id=HUB_S5,
            skill="listening",
            today=TODAY,
        )
    assert a == b == "filled"
    assert (str(USER_A), SET_S5) in store.claims
    assert (str(USER_B), SET_S5) in store.claims
