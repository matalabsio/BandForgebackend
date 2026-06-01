"""Unit tests for mock orchestration helpers (sequential unlock, part completion)."""

from uuid import UUID

from app.services.mock_orchestrator import (
    _compute_module_statuses,
    _module_parts_complete,
)

# Valid UUID placeholder (catalog uses mnemonic m000… string in DB migrations).
M01 = UUID("a0000000-0000-4000-8000-000000000001")


def _modules_config():
    return [
        {
            "module": "listening",
            "sequence_order": 1,
            "duration_minutes": 30,
            "is_enabled": True,
        },
        {
            "module": "reading",
            "sequence_order": 2,
            "duration_minutes": 30,
            "is_enabled": True,
        },
        {
            "module": "writing",
            "sequence_order": 3,
            "duration_minutes": 60,
            "is_enabled": False,
        },
    ]


def test_module_parts_complete_requires_all_live_parts():
    from unittest.mock import patch

    attempts = [
        {"module": "reading", "status": "completed", "part": 1},
    ]
    with patch(
        "app.services.mock_orchestrator.repo.live_question_parts",
        return_value=[1, 2],
    ):
        assert not _module_parts_complete(
            mock_test_id=M01,
            module="reading",
            module_attempts=attempts,
        )
        attempts.append({"module": "reading", "status": "completed", "part": 2})
        assert _module_parts_complete(
            mock_test_id=M01,
            module="reading",
            module_attempts=attempts,
        )


def test_module_parts_complete_test1_only_part_one_required():
    from unittest.mock import patch

    with patch(
        "app.services.mock_orchestrator.repo.live_question_parts",
        return_value=[1],
    ):
        assert _module_parts_complete(
            mock_test_id=M01,
            module="reading",
            module_attempts=[
                {"module": "reading", "status": "completed", "part": 1},
            ],
        )
        assert _module_parts_complete(
            mock_test_id=M01,
            module="listening",
            module_attempts=[
                {"module": "listening", "status": "completed", "part": 1},
            ],
        )


def test_compute_module_statuses_sequential_lock():
    from unittest.mock import patch

    modules = _modules_config()
    with patch(
        "app.services.mock_orchestrator.repo.live_question_parts",
        side_effect=lambda mock_test_id, module: [1, 2] if module == "reading" else [1, 2, 3, 4],
    ):
        statuses = _compute_module_statuses(
            mock_test_id=M01,
            modules=modules,
            module_attempts=[],
        )
    by_mod = {s.module: s.status for s in statuses}
    assert by_mod["listening"] == "available"
    assert by_mod["reading"] == "locked"


def test_compute_module_statuses_unlocks_reading_after_listening_done():
    from unittest.mock import patch

    modules = _modules_config()
    attempts = [
        {
            "id": "11111111-1111-4111-8111-111111111101",
            "module": "listening",
            "status": "completed",
            "part": 1,
            "completed_at": "2026-01-01",
        },
        {
            "id": "11111111-1111-4111-8111-111111111102",
            "module": "listening",
            "status": "completed",
            "part": 2,
            "completed_at": "2026-01-02",
        },
        {
            "id": "11111111-1111-4111-8111-111111111103",
            "module": "listening",
            "status": "completed",
            "part": 3,
            "completed_at": "2026-01-03",
        },
        {
            "id": "11111111-1111-4111-8111-111111111104",
            "module": "listening",
            "status": "completed",
            "part": 4,
            "completed_at": "2026-01-04",
        },
    ]
    scores = {
        "11111111-1111-4111-8111-111111111101": {"band": 7.0},
        "11111111-1111-4111-8111-111111111102": {"band": 7.0},
        "11111111-1111-4111-8111-111111111103": {"band": 7.0},
        "11111111-1111-4111-8111-111111111104": {"band": 7.0},
    }
    with patch(
        "app.services.mock_orchestrator.repo.live_question_parts",
        side_effect=lambda mock_test_id, module: [1, 2, 3, 4]
        if module == "reading"
        else [1, 2, 3, 4],
    ):
        statuses = _compute_module_statuses(
            mock_test_id=M01,
            modules=modules,
            module_attempts=attempts,
            scores_by_attempt=scores,
        )
    by_mod = {s.module: s.status for s in statuses}
    assert by_mod["listening"] == "completed"
    assert by_mod["reading"] == "available"


def test_compute_module_statuses_listening_complete_after_part_one_only():
    """Test 1 live config: one listening part done does not complete module."""
    from unittest.mock import patch

    modules = _modules_config()
    attempts = [
        {
            "id": "11111111-1111-4111-8111-111111111101",
            "module": "listening",
            "status": "completed",
            "part": 1,
            "completed_at": "2026-01-01",
        },
    ]
    scores = {"11111111-1111-4111-8111-111111111101": {"band": 6.5}}
    with patch(
        "app.services.mock_orchestrator.repo.live_question_parts",
        side_effect=lambda mock_test_id, module: [1, 2, 3, 4],
    ):
        statuses = _compute_module_statuses(
            mock_test_id=M01,
            modules=modules,
            module_attempts=attempts,
            scores_by_attempt=scores,
        )
    by_mod = {s.module: s.status for s in statuses}
    assert by_mod["listening"] == "in_progress"
    assert by_mod["reading"] == "locked"


def test_assert_module_unlocked_allows_next_reading_passage_after_partial():
    from unittest.mock import patch

    from app.services.mock_orchestrator import assert_module_unlocked

    user_id = UUID("22222222-2222-4222-8222-222222222222")
    mock_attempt_id = UUID("33333333-3333-4333-8333-333333333333")
    modules = _modules_config()

    with (
        patch(
            "app.services.mock_orchestrator._assert_mock_attempt_owner",
            return_value={"id": str(mock_attempt_id)},
        ),
        patch(
            "app.services.mock_orchestrator.repo.list_mock_modules",
            return_value=modules,
        ),
        patch(
            "app.services.mock_orchestrator.repo.list_module_attempts",
            return_value=[
                {
                    "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
                    "module": "reading",
                    "status": "completed",
                    "part": 1,
                },
            ],
        ),
        patch(
            "app.services.mock_orchestrator.repo.live_question_parts",
            return_value=[1, 2, 3, 4],
        ),
    ):
        assert_module_unlocked(
            mock_attempt_id=mock_attempt_id,
            user_id=user_id,
            mock_test_id=M01,
            module="reading",
            part=2,
        )


def _start_ctx(*, modules=None, in_progress=None):
    return {
        "mock_test": {
            "id": str(M01),
            "title": "Test",
            "description": None,
            "is_published": True,
        },
        "modules": modules if modules is not None else _modules_config(),
        "in_progress_attempt": in_progress,
    }


def _progress_bundle(
    *,
    mock_attempt_id: str = "33333333-3333-4333-8333-333333333333",
    module_attempts=None,
):
    return {
        "mock_attempt": {
            "id": mock_attempt_id,
            "user_id": "22222222-2222-4222-8222-222222222222",
            "mock_test_id": str(M01),
            "status": "in_progress",
            "started_at": "2026-01-01T00:00:00+00:00",
            "current_module": None,
        },
        "modules": _modules_config(),
        "module_attempts": module_attempts or [],
        "module_scores": [],
    }


def _sample_progress(*, current_module: str = "listening", next_module: str = "listening"):
    from datetime import UTC, datetime

    from app.schemas.mock_orchestrator import MockAttemptProgress, ModuleProgress

    return MockAttemptProgress(
        mock_attempt_id=UUID("33333333-3333-4333-8333-333333333333"),
        mock_test_id=M01,
        status="in_progress",
        started_at=datetime.now(UTC),
        current_module=current_module,  # type: ignore[arg-type]
        next_module=next_module,  # type: ignore[arg-type]
        next_part=1,
        modules=[
            ModuleProgress(
                module=current_module,  # type: ignore[arg-type]
                sequence_order=1,
                status="in_progress",
                duration_minutes=30,
                is_enabled=True,
                part=1,
            ),
        ],
    )


def test_start_mock_fresh_m01_opens_listening_part_one():
    """Fresh Test 1 attempt always starts listening part 1."""
    from unittest.mock import MagicMock, patch

    from app.services.mock_orchestrator import start_mock

    user_id = UUID("22222222-2222-4222-8222-222222222222")
    modules = _modules_config()

    with (
        patch(
            "app.services.mock_orchestrator.repo.fetch_mock_start_context",
            return_value=_start_ctx(modules=modules),
        ),
        patch(
            "app.services.mock_orchestrator.repo.insert_mock_attempt",
            return_value={"id": "33333333-3333-4333-8333-333333333333"},
        ),
        patch(
            "app.services.mock_orchestrator.repo.fetch_mock_attempt_progress_bundle",
            return_value=_progress_bundle(),
        ),
        patch(
            "app.services.mock_orchestrator.repo.live_question_parts",
            return_value=[1],
        ),
        patch(
            "app.services.mock_orchestrator._start_module_attempt",
            return_value=(UUID("44444444-4444-4444-8444-444444444444"), 1),
        ) as start_mod,
        patch("app.services.mock_orchestrator.repo.update_mock_attempt"),
    ):
        res = start_mock(mock_test_id=M01, user_id=user_id, force_new=False)

    assert res.current_module == "listening"
    assert res.part == 1
    assert res.progress is not None
    assert res.progress.next_module == "listening"
    start_mod.assert_called_once()
    assert start_mod.call_args.kwargs["module"] == "listening"
    assert start_mod.call_args.kwargs["part"] == 1


def test_start_mock_targets_listening_first():
    """start_mock should open listening when no attempts exist."""
    from unittest.mock import MagicMock, patch

    from app.services.mock_orchestrator import start_mock

    user_id = UUID("22222222-2222-4222-8222-222222222222")
    modules = _modules_config()

    with (
        patch(
            "app.services.mock_orchestrator.repo.fetch_mock_start_context",
            return_value=_start_ctx(modules=modules),
        ),
        patch(
            "app.services.mock_orchestrator.repo.insert_mock_attempt",
            return_value={"id": "33333333-3333-4333-8333-333333333333"},
        ),
        patch(
            "app.services.mock_orchestrator.repo.fetch_mock_attempt_progress_bundle",
            return_value=_progress_bundle(),
        ),
        patch(
            "app.services.mock_orchestrator.repo.live_question_parts",
            return_value=[1],
        ),
        patch(
            "app.services.mock_orchestrator._start_module_attempt",
            return_value=(UUID("44444444-4444-4444-8444-444444444444"), 1),
        ),
        patch("app.services.mock_orchestrator.repo.update_mock_attempt"),
    ):
        res = start_mock(mock_test_id=M01, user_id=user_id, force_new=False)

    assert res.current_module == "listening"
    assert res.progress is not None
    assert res.part == 1
    assert res.resumed is False


def test_m01_live_parts():
    from app.mock_catalog.constants import M01_MOCK_TEST_ID, MODULE_LIVE_PARTS

    assert MODULE_LIVE_PARTS[M01_MOCK_TEST_ID]["listening"] == (1,)
    assert MODULE_LIVE_PARTS[M01_MOCK_TEST_ID]["reading"] == (1,)
    assert MODULE_LIVE_PARTS[M01_MOCK_TEST_ID]["writing"] == (1,)


def test_assert_module_unlocked_rejects_completed_listening_part():
    from unittest.mock import patch

    import pytest
    from fastapi import HTTPException

    from app.services.mock_orchestrator import assert_module_unlocked

    user_id = UUID("22222222-2222-4222-8222-222222222222")
    mock_attempt_id = UUID("33333333-3333-4333-8333-333333333333")
    modules = _modules_config()

    with (
        patch(
            "app.services.mock_orchestrator._assert_mock_attempt_owner",
            return_value={"id": str(mock_attempt_id)},
        ),
        patch(
            "app.services.mock_orchestrator.repo.list_mock_modules",
            return_value=modules,
        ),
        patch(
            "app.services.mock_orchestrator.repo.list_module_attempts",
            return_value=[
                {
                    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
                    "module": "listening",
                    "status": "completed",
                    "part": 1,
                },
            ],
        ),
        patch(
            "app.services.mock_orchestrator.repo.live_question_parts",
            return_value=[1, 2, 3, 4],
        ),
        patch(
            "app.services.mock_orchestrator._compute_module_statuses",
        ) as mock_statuses,
    ):
        listening = type(
            "MP",
            (),
            {"module": "listening", "status": "available"},
        )()
        mock_statuses.return_value = [listening]

        with pytest.raises(HTTPException) as exc:
            assert_module_unlocked(
                mock_attempt_id=mock_attempt_id,
                user_id=user_id,
                mock_test_id=M01,
                module="listening",
                part=1,
            )
        assert exc.value.status_code == 403


def test_assert_module_unlocked_allows_next_listening_part():
    from unittest.mock import patch

    from app.services.mock_orchestrator import assert_module_unlocked

    user_id = UUID("22222222-2222-4222-8222-222222222222")
    mock_attempt_id = UUID("33333333-3333-4333-8333-333333333333")
    modules = _modules_config()

    with (
        patch(
            "app.services.mock_orchestrator._assert_mock_attempt_owner",
            return_value={"id": str(mock_attempt_id)},
        ),
        patch(
            "app.services.mock_orchestrator.repo.list_mock_modules",
            return_value=modules,
        ),
        patch(
            "app.services.mock_orchestrator.repo.list_module_attempts",
            return_value=[
                {
                    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
                    "module": "listening",
                    "status": "completed",
                    "part": 1,
                },
            ],
        ),
        patch(
            "app.services.mock_orchestrator.repo.live_question_parts",
            return_value=[1, 2, 3, 4],
        ),
        patch(
            "app.services.mock_orchestrator._compute_module_statuses",
        ) as mock_statuses,
    ):
        listening = type(
            "MP",
            (),
            {"module": "listening", "status": "available"},
        )()
        mock_statuses.return_value = [listening]

        assert_module_unlocked(
            mock_attempt_id=mock_attempt_id,
            user_id=user_id,
            mock_test_id=M01,
            module="listening",
            part=2,
        )


def test_get_mock_session_prefers_in_progress():
    from unittest.mock import MagicMock, patch

    from app.services.mock_orchestrator import get_mock_session

    user_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    attempt_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    progress = MagicMock()
    progress.model_dump.return_value = {"mock_attempt_id": str(attempt_id)}

    with (
        patch("app.services.mock_orchestrator.get_json", return_value=None),
        patch("app.services.mock_orchestrator.set_json"),
        patch("app.services.mock_orchestrator.delete_many"),
        patch(
            "app.services.mock_orchestrator.repo.find_in_progress_mock_attempt",
            return_value={"id": str(attempt_id)},
        ),
        patch(
            "app.services.mock_orchestrator.repo.list_user_mock_attempts",
        ) as mock_history,
        patch(
            "app.services.mock_orchestrator.get_progress",
            return_value=progress,
        ) as mock_progress,
    ):
        result = get_mock_session(mock_test_id=M01, user_id=user_id)

    assert result is progress
    mock_history.assert_not_called()
    mock_progress.assert_called_once_with(
        mock_attempt_id=attempt_id,
        user_id=user_id,
    )
