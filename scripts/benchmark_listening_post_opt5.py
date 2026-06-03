"""Listening start/submit benchmark after orchestration optimizations (#1–#5).

Usage:
  cd backend && source .venv/bin/activate
  python -m scripts.benchmark_listening_post_opt5
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any
from uuid import UUID

from app.cache.hybrid_cache import delete_many, get_json
from app.cache.mock_cache import progress_cache_key, read_unlock_snapshot
from app.listening import repository as repo
from app.listening import service
from app.listening.schemas import ListeningQuestionsResponse
from app.mock_catalog.constants import M01_MOCK_TEST_ID
from app.services import mock_orchestrator
from app.services import mock_orchestrator_repository as mor

M01 = UUID(M01_MOCK_TEST_ID)

# Fixtures (dev Supabase)
FIXTURES = {
    "p1_abandoned": {
        "user_id": UUID("1675102d-451d-406b-ab9c-333d7deba44e"),
        "mock_attempt_id": UUID("8c752e91-dc99-47db-9197-c4ee2d648220"),
    },
    "p2_after_p1": {
        "user_id": UUID("c982bca0-fc54-4aea-bc74-23a8b3ce6aa7"),
        "mock_attempt_id": UUID("c46f296d-3c40-4ae4-8b9a-5e067ada9627"),
    },
}


def _ms(start: float) -> int:
    return round((perf_counter() - start) * 1000)


def _bust(*, user_id: UUID, mock_attempt_id: UUID | None, part: int, unlock: bool, questions: bool) -> None:
    keys: list[str] = []
    if questions:
        keys.append(f"listening_questions:{M01}:{part}")
    if unlock and mock_attempt_id is not None:
        keys.append(progress_cache_key(mock_attempt_id=mock_attempt_id, user_id=user_id))
        keys.append(f"mock_session:{user_id}:{M01}")
    if keys:
        delete_many(keys)


def _profile_questions_phases(
    *,
    mock_test_id: UUID,
    user_id: UUID,
    part: int,
    test_row: dict[str, Any],
    attempt: dict[str, Any],
) -> dict[str, Any]:
    cache_key = f"listening_questions:{mock_test_id}:{part}"
    cached = get_json(cache_key)
    if isinstance(cached, dict):
        return {
            "questions_source": "cache",
            "list_questions_ms": 0,
            "display_offsets_ms": 0,
            "presign_ms": 0,
            "serialize_ms": 0,
            "questions_total_ms": 0,
        }

    t0 = perf_counter()
    rows = repo.list_questions_public(mock_test_id, part=part)
    list_ms = _ms(t0)

    t0 = perf_counter()
    display_offsets = repo.part_display_offsets(mock_test_id=mock_test_id)
    offsets_ms = _ms(t0)

    presigned: dict[str, str | None] = {}
    t0 = perf_counter()
    for row in rows:
        raw = row.get("audio_url")
        if raw and raw not in presigned:
            presigned[raw] = service._presign_audio(raw)
    presign_ms = _ms(t0)

    t0 = perf_counter()
    ListeningQuestionsResponse.model_validate(
        service.get_session_questions(
            mock_test_id=mock_test_id,
            user_id=user_id,
            part=part,
            test_row=test_row,
            attempt=attempt,
        ).model_dump(mode="json")
    )
    serialize_ms = _ms(t0)

    return {
        "questions_source": "db",
        "list_questions_ms": list_ms,
        "display_offsets_ms": offsets_ms,
        "presign_ms": presign_ms,
        "serialize_ms": serialize_ms,
        "questions_total_ms": list_ms + offsets_ms + presign_ms + serialize_ms,
        "display_offsets": display_offsets,
    }


def profile_start(
    *,
    label: str,
    user_id: UUID,
    part: int,
    mock_attempt_id: UUID | None,
    warm_unlock_from_submit: bool,
    bust_unlock: bool,
    bust_questions: bool,
) -> dict[str, Any]:
    _bust(
        user_id=user_id,
        mock_attempt_id=mock_attempt_id,
        part=part,
        unlock=bust_unlock,
        questions=bust_questions,
    )
    if warm_unlock_from_submit and mock_attempt_id is not None:
        mock_orchestrator._finalize_mock_progress_after_submit(
            mock_attempt_id=mock_attempt_id,
            mock_test_id=M01,
            user_id=user_id,
        )

    unlock_before = (
        read_unlock_snapshot(mock_attempt_id=mock_attempt_id, user_id=user_id)
        if mock_attempt_id
        else None
    )
    qkey = f"listening_questions:{M01}:{part}"
    questions_before = get_json(qkey)

    result: dict[str, Any] = {
        "label": label,
        "part": part,
        "unlock_source_before": "cache" if unlock_before else "db",
        "questions_source_before": "cache" if isinstance(questions_before, dict) else "db",
    }

    t_total = perf_counter()
    t0 = perf_counter()
    test_row = repo.get_mock_test(M01, allow_unpublished=True)
    result["get_mock_test_ms"] = _ms(t0)

    unlock_ms = 0
    if mock_attempt_id is not None:
        t0 = perf_counter()
        mock_orchestrator.assert_module_unlocked(
            mock_attempt_id=mock_attempt_id,
            user_id=user_id,
            mock_test_id=M01,
            module="listening",
            part=part,
        )
        unlock_ms = _ms(t0)
    result["unlock_ms"] = unlock_ms
    result["unlock_source"] = result["unlock_source_before"]

    t0 = perf_counter()
    existing = repo.find_in_progress_listening_attempt(
        user_id=user_id,
        mock_test_id=M01,
        part=part,
        mock_attempt_id=mock_attempt_id,
    )
    result["find_attempt_ms"] = _ms(t0)
    result["attempt_action"] = "resume" if existing else "create"

    t0 = perf_counter()
    if existing:
        resp = service.start_attempt(
            mock_test_id=M01,
            user_id=user_id,
            part=part,
            mock_attempt_id=mock_attempt_id,
            include_questions=True,
        )
    else:
        resp = service.start_attempt(
            mock_test_id=M01,
            user_id=user_id,
            part=part,
            mock_attempt_id=mock_attempt_id,
            include_questions=True,
        )
    result["start_service_ms"] = _ms(t0)
    result["duration_ms"] = _ms(t_total)
    result["resumed"] = resp.resumed

    attempt_row = existing or repo.find_in_progress_listening_attempt(
        user_id=user_id,
        mock_test_id=M01,
        part=part,
        mock_attempt_id=mock_attempt_id,
    )
    if attempt_row and bust_questions:
        q_phases = _profile_questions_phases(
            mock_test_id=M01,
            user_id=user_id,
            part=part,
            test_row=test_row,
            attempt=attempt_row,
        )
        result.update(q_phases)
    else:
        result["questions_source"] = (
            "cache" if isinstance(get_json(qkey), dict) else "db"
        )

    return result


def main() -> None:
    scenarios = [
        profile_start(
            label="part1_cold_orchestrated",
            user_id=FIXTURES["p1_abandoned"]["user_id"],
            part=1,
            mock_attempt_id=FIXTURES["p1_abandoned"]["mock_attempt_id"],
            warm_unlock_from_submit=False,
            bust_unlock=True,
            bust_questions=True,
        ),
        profile_start(
            label="part2_after_p1_submit_unlock_warm",
            user_id=FIXTURES["p2_after_p1"]["user_id"],
            part=2,
            mock_attempt_id=FIXTURES["p2_after_p1"]["mock_attempt_id"],
            warm_unlock_from_submit=True,
            bust_unlock=False,
            bust_questions=True,
        ),
        profile_start(
            label="part2_fully_warm_repeat",
            user_id=FIXTURES["p2_after_p1"]["user_id"],
            part=2,
            mock_attempt_id=FIXTURES["p2_after_p1"]["mock_attempt_id"],
            warm_unlock_from_submit=False,
            bust_unlock=False,
            bust_questions=False,
        ),
    ]

    # Part 3: questions path only (no mock with P1+P2 done in DB)
    p3_user = FIXTURES["p2_after_p1"]["user_id"]
    test_row = repo.get_mock_test(M01, allow_unpublished=True)
    attempt = repo.find_in_progress_listening_attempt(
        user_id=p3_user,
        mock_test_id=M01,
        part=2,
        mock_attempt_id=FIXTURES["p2_after_p1"]["mock_attempt_id"],
    ) or {"mock_attempt_id": str(FIXTURES["p2_after_p1"]["mock_attempt_id"])}
    delete_many([f"listening_questions:{M01}:3"])
    p3_questions = _profile_questions_phases(
        mock_test_id=M01,
        user_id=p3_user,
        part=3,
        test_row=test_row,
        attempt=attempt,
    )
    p3_questions["label"] = "part3_questions_cold_only"
    p3_questions["note"] = "Full part3 start blocked: no fixture with parts 1–2 completed"

    print(json.dumps({"scenarios": scenarios, "part3_isolated": p3_questions}, indent=2))


if __name__ == "__main__":
    main()
