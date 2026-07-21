"""Module-complete review rollup across listening parts and reading passages."""

from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.mock_catalog.constants import M01_MOCK_TEST_ID, M02_MOCK_TEST_ID
from app.schemas.mock_orchestrator import MockAttemptProgress
from app.services import module_review

M01 = UUID(M01_MOCK_TEST_ID)
M02 = UUID(M02_MOCK_TEST_ID)
USER = UUID("22222222-2222-4222-8222-222222222222")
MOCK_ATTEMPT = UUID("33333333-3333-4333-8333-333333333333")


def _uuid(seed: int) -> str:
    return f"dddddddd-dddd-4ddd-8ddd-{seed:012d}"


def _attempt(module: str, part: int) -> dict:
    return {
        "id": _uuid(part),
        "module": module,
        "status": "completed",
        "part": part,
    }


def _fake_progress(next_module: str = "reading") -> MockAttemptProgress:
    from datetime import UTC, datetime

    return MockAttemptProgress(
        mock_attempt_id=MOCK_ATTEMPT,
        mock_test_id=M01,
        status="in_progress",
        started_at=datetime.now(UTC),
        next_module=next_module,  # type: ignore[arg-type]
        next_part=1,
    )


def _q(seed: int, number: int, qtype: str, correct: str) -> dict:
    return {
        "id": _uuid(1000 + seed),
        "question_number": number,
        "question_type": qtype,
        "prompt": f"Question {number}",
        "correct_answer": correct,
    }


def test_listening_module_review_rolls_up_all_parts():
    module_attempts = [_attempt("listening", p) for p in (1, 2, 3, 4)]

    def questions_for(mock_test_id, part):  # noqa: ARG001
        return [
            _q(part * 10 + 1, 1, "mcq", "A"),
            _q(part * 10 + 2, 2, "sentence_completion", "cat"),
        ]

    with (
        patch.object(
            module_review.mock_orchestrator,
            "_load_mock_attempt_context",
            return_value=({}, M01, [], module_attempts, {}),
        ),
        patch.object(
            module_review.mock_orchestrator,
            "_progress_from_context",
            return_value=_fake_progress("reading"),
        ),
        patch.object(
            module_review.listening_repo,
            "part_display_offsets",
            return_value={1: 0, 2: 10, 3: 20, 4: 30},
        ),
        patch.object(
            module_review.listening_repo,
            "list_questions_for_review",
            side_effect=questions_for,
        ),
        patch.object(
            module_review.listening_repo,
            "list_answers_for_attempt",
            return_value=[],
        ),
    ):
        result = module_review.get_module_review(
            mock_attempt_id=MOCK_ATTEMPT, module="listening", user_id=USER
        )

    assert result.module == "listening"
    assert len(result.groups) == 4
    assert result.total_questions == 8
    assert result.raw_score == 0  # no answers → all incorrect
    assert result.groups[0].label == "Part 1"
    assert result.groups[1].questions[0].question_number == 11
    assert result.next_module == "reading"


def test_listening_module_review_scores_stored_correct_flag():
    module_attempts = [_attempt("listening", p) for p in (1, 2, 3, 4)]

    def questions_for(mock_test_id, part):  # noqa: ARG001
        return [_q(part, 1, "mcq", "A")]

    def answers_for(attempt_id):
        # attempt id part is the last segment number
        return [
            {
                "question_id": _uuid(1000 + int(str(attempt_id).split("-")[-1])),
                "user_answer": "A",
                "is_correct": True,
            }
        ]

    with (
        patch.object(
            module_review.mock_orchestrator,
            "_load_mock_attempt_context",
            return_value=({}, M01, [], module_attempts, {}),
        ),
        patch.object(
            module_review.mock_orchestrator,
            "_progress_from_context",
            return_value=_fake_progress("reading"),
        ),
        patch.object(
            module_review.listening_repo,
            "part_display_offsets",
            return_value={1: 0, 2: 10, 3: 20, 4: 30},
        ),
        patch.object(
            module_review.listening_repo,
            "list_questions_for_review",
            side_effect=questions_for,
        ),
        patch.object(
            module_review.listening_repo,
            "list_answers_for_attempt",
            side_effect=answers_for,
        ),
    ):
        result = module_review.get_module_review(
            mock_attempt_id=MOCK_ATTEMPT, module="listening", user_id=USER
        )

    assert result.raw_score == 4
    assert result.total_questions == 4


def test_reading_module_review_groups_by_passage_and_section():
    module_attempts = [_attempt("reading", p) for p in (1, 2)]

    def questions_for(mock_test_id, part):  # noqa: ARG001
        return [
            _q(part * 10 + 1, 1, "tfng", "TRUE"),
            _q(part * 10 + 2, 2, "tfng", "FALSE"),
            _q(part * 10 + 3, 3, "matching_headings", "i"),
            _q(part * 10 + 4, 4, "sentence_completion", "water"),
        ]

    with (
        patch.object(
            module_review.mock_orchestrator,
            "_load_mock_attempt_context",
            return_value=({}, M01, [], module_attempts, {}),
        ),
        patch.object(
            module_review.mock_orchestrator,
            "_progress_from_context",
            return_value=_fake_progress("writing"),
        ),
        patch.object(
            module_review.reading_repo,
            "display_offset_before_part",
            side_effect=lambda mock_test_id, part: (part - 1) * 4,
        ),
        patch.object(
            module_review.reading_repo,
            "list_questions_for_review",
            side_effect=questions_for,
        ),
        patch.object(
            module_review.reading_repo,
            "list_answers_for_attempt",
            return_value=[],
        ),
    ):
        result = module_review.get_module_review(
            mock_attempt_id=MOCK_ATTEMPT, module="reading", user_id=USER
        )

    assert result.module == "reading"
    assert len(result.groups) == 6  # 2 passages x 3 section types
    assert result.total_questions == 8
    assert result.groups[0].label == "Passage 1 · True / False / Not Given"
    assert result.groups[1].label == "Passage 1 · Matching Headings"
    assert result.groups[2].label == "Passage 1 · Sentence Completion"
    assert result.groups[3].questions[0].question_number == 5  # passage 2 offset
    assert result.next_module == "writing"


def test_reading_m02_passage_three_uses_ynng_label():
    module_attempts = [_attempt("reading", p) for p in (1, 2, 3)]

    with (
        patch.object(
            module_review.mock_orchestrator,
            "_load_mock_attempt_context",
            return_value=({}, M02, [], module_attempts, {}),
        ),
        patch.object(
            module_review.mock_orchestrator,
            "_progress_from_context",
            return_value=_fake_progress("writing"),
        ),
        patch.object(
            module_review.reading_repo,
            "display_offset_before_part",
            side_effect=lambda mock_test_id, part: part - 1,
        ),
        patch.object(
            module_review.reading_repo,
            "list_questions_for_review",
            side_effect=lambda mock_test_id, part: [_q(part, 1, "tfng", "YES")],
        ),
        patch.object(
            module_review.reading_repo,
            "list_answers_for_attempt",
            return_value=[],
        ),
    ):
        result = module_review.get_module_review(
            mock_attempt_id=MOCK_ATTEMPT, module="reading", user_id=USER
        )

    labels = [g.label for g in result.groups]
    assert "Passage 3 · Yes / No / Not Given" in labels


def test_module_review_requires_all_parts_complete():
    module_attempts = [_attempt("listening", p) for p in (1, 2)]  # missing 3, 4

    with patch.object(
        module_review.mock_orchestrator,
        "_load_mock_attempt_context",
        return_value=({}, M01, [], module_attempts, {}),
    ):
        with pytest.raises(HTTPException) as exc:
            module_review.get_module_review(
                mock_attempt_id=MOCK_ATTEMPT, module="listening", user_id=USER
            )
    assert exc.value.status_code == 409


def test_module_review_rejects_unsupported_module():
    with pytest.raises(HTTPException) as exc:
        module_review.get_module_review(
            mock_attempt_id=MOCK_ATTEMPT, module="writing", user_id=USER
        )
    assert exc.value.status_code == 400


def test_speaking_module_review_matches_authoritative_release():
    attempt_id = UUID(_uuid(77))
    summary = {
        **_attempt("speaking", 1),
        "id": str(attempt_id),
        "completed_at": "2026-07-21T06:00:00Z",
    }
    full_attempt = {
        **summary,
        "user_id": str(USER),
        "mock_test_id": str(M01),
        "mock_attempt_id": str(MOCK_ATTEMPT),
        "speaking_manifest": [
            {
                "id": _uuid(901),
                "prompt": "Tell me about your hometown.",
                "options": {"duration_hint_sec": 45},
            }
        ],
    }
    review = {
        "id": _uuid(902),
        "status": "completed",
        "human_band": 7.0,
        "human_criteria_scores": {
            "fluency": 7.0,
            "lexical": 7.0,
            "grammar": 7.0,
            "pronunciation": 7.0,
        },
        "ai_scores": {"status": "ai_failed", "ai_band": 5.5},
        "evaluation_status": "failed",
        "released_at": "2026-07-21T06:30:00Z",
        "approval_version": 1,
        "reviewer_display_name": "Public Examiner",
        "reviewer_credential_label": "Certified IELTS Examiner",
    }

    with (
        patch.object(
            module_review.mock_orchestrator,
            "_load_mock_attempt_context",
            return_value=({}, M01, [], [summary], {}),
        ),
        patch.object(
            module_review.mock_orchestrator,
            "_progress_from_context",
            return_value=_fake_progress("speaking"),
        ),
        patch.object(
            module_review.speaking_repo,
            "get_attempt",
            return_value=full_attempt,
        ),
        patch.object(
            module_review.speaking_repo,
            "get_speaking_review_for_attempt",
            return_value=review,
        ),
        patch.object(
            module_review.speaking_repo,
            "list_speaking_responses",
            return_value=[{"duration_sec": 40}],
        ),
        patch.object(
            module_review.speaking_repo,
            "transcription_progress",
            return_value={"total": 1, "completed": 0, "failed": 1},
        ),
    ):
        result = module_review.get_speaking_module_review(
            mock_attempt_id=MOCK_ATTEMPT,
            user_id=USER,
        )

    assert result.release_state == "released"
    assert result.report_available is True
    assert result.result_route == "report"
    assert result.overall_band == 7.0
    assert result.ai_band is None
    assert result.score_source == "human"
    assert result.reviewer is not None
    assert result.reviewer.display_name == "Public Examiner"


def test_speaking_module_review_only_exposes_completed_ai_evaluation():
    attempt_id = UUID(_uuid(78))
    summary = {
        **_attempt("speaking", 1),
        "id": str(attempt_id),
        "completed_at": "2026-07-21T06:00:00Z",
    }
    full_attempt = {
        **summary,
        "user_id": str(USER),
        "mock_test_id": str(M01),
        "mock_attempt_id": str(MOCK_ATTEMPT),
        "speaking_manifest": [
            {
                "id": _uuid(903),
                "prompt": "Tell me about your hometown.",
                "options": {"duration_hint_sec": 45},
            }
        ],
    }
    complete_review = {
        "id": _uuid(904),
        "status": "pending",
        "human_band": None,
        "ai_scores": {
            "status": "ai_complete",
            "ai_band": 6.5,
            "fluency": 6.0,
            "lexical": 6.5,
            "grammar": 6.0,
            "pronunciation": 6.5,
            "evaluation": {
                "strengths": ["Clear examples"],
                "improvements": ["Extend Part 3 answers"],
                "next_band_advice": "Use one example and one contrast.",
            },
        },
        "evaluation_status": "completed",
    }

    with (
        patch.object(
            module_review.mock_orchestrator,
            "_load_mock_attempt_context",
            return_value=({}, M01, [], [summary], {}),
        ),
        patch.object(
            module_review.mock_orchestrator,
            "_progress_from_context",
            return_value=_fake_progress("speaking"),
        ),
        patch.object(
            module_review.speaking_repo,
            "get_attempt",
            return_value=full_attempt,
        ),
        patch.object(
            module_review.speaking_repo,
            "get_speaking_review_for_attempt",
            return_value=complete_review,
        ),
        patch.object(
            module_review.speaking_repo,
            "list_speaking_responses",
            return_value=[{"duration_sec": 40}],
        ),
        patch.object(
            module_review.speaking_repo,
            "transcription_progress",
            return_value={"total": 1, "completed": 1, "failed": 0},
        ),
    ):
        result = module_review.get_speaking_module_review(
            mock_attempt_id=MOCK_ATTEMPT,
            user_id=USER,
        )

    assert result.ai_band == 6.5
    assert result.score_source == "ai_estimate"
    assert result.criteria["fluency"] == 6.0
    assert result.strengths == ["Clear examples"]
    assert result.next_band_advice == "Use one example and one contrast."

    stale_review = {
        **complete_review,
        "evaluation_status": "not_queued",
        "ai_scores": {"status": "pending_multi_response", "ai_band": 8.0},
    }
    with (
        patch.object(
            module_review.mock_orchestrator,
            "_load_mock_attempt_context",
            return_value=({}, M01, [], [summary], {}),
        ),
        patch.object(
            module_review.mock_orchestrator,
            "_progress_from_context",
            return_value=_fake_progress("speaking"),
        ),
        patch.object(module_review.speaking_repo, "get_attempt", return_value=full_attempt),
        patch.object(
            module_review.speaking_repo,
            "get_speaking_review_for_attempt",
            return_value=stale_review,
        ),
        patch.object(
            module_review.speaking_repo,
            "list_speaking_responses",
            return_value=[{"duration_sec": 40}],
        ),
        patch.object(
            module_review.speaking_repo,
            "transcription_progress",
            return_value={"total": 1, "completed": 1, "failed": 0},
        ),
    ):
        stale = module_review.get_speaking_module_review(
            mock_attempt_id=MOCK_ATTEMPT,
            user_id=USER,
        )

    assert stale.ai_band is None
    assert stale.score_source == "processing"
