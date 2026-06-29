"""Evaluator portal writing band math and schema tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.admin.schemas import (
    ApproveWritingRequest,
    PatchWritingReviewRequest,
    WritingHumanCriteriaScores,
    WritingReviewDetail,
    WritingSubmissionMeta,
)
from app.admin.writing import approve_writing_review
from app.admin.writing_band import (
    ai_scores_to_criteria,
    compute_overall_band,
    normalize_criteria_scores,
)

REVIEW_ID = UUID("11111111-1111-4111-8111-111111111111")
ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")
MOCK_ATTEMPT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
MOCK_TEST_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ADMIN_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


def _table_chain(data=None, count=None):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.update.return_value = chain
    chain.upsert.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.neq.return_value = chain
    result = MagicMock()
    result.data = data if data is not None else []
    result.count = count
    chain.execute.return_value = result
    return chain


def test_approve_writing_review_invalidates_student_caches():
    existing_chain = _table_chain([{"id": str(REVIEW_ID), "status": "pending"}])
    attempt_id_chain = _table_chain([{"attempt_id": str(ATTEMPT_ID)}])
    attempt_row_chain = _table_chain(
        [
            {
                "user_id": str(USER_ID),
                "mock_attempt_id": str(MOCK_ATTEMPT_ID),
                "mock_test_id": str(MOCK_TEST_ID),
            }
        ]
    )
    update_chain = _table_chain()
    upsert_chain = _table_chain()
    pending_mock_chain = _table_chain(count=1)
    pending_diag_chain = _table_chain(count=0)

    mock_client = MagicMock()

    def table_side_effect(name):
        if name == "writing_reviews":
            calls = table_side_effect.writing_calls
            table_side_effect.writing_calls += 1
            if calls == 0:
                return existing_chain
            if calls == 1:
                return update_chain
            return attempt_id_chain
        if name == "module_scores":
            return upsert_chain
        if name == "test_attempts":
            return attempt_row_chain
        if name == "diagnostic_review_submissions":
            return pending_diag_chain
        return pending_mock_chain

    table_side_effect.writing_calls = 0
    mock_client.table.side_effect = table_side_effect

    detail = WritingReviewDetail(
        id=REVIEW_ID,
        source="mock",
        attempt_id=ATTEMPT_ID,
        status="completed",
        submission_meta=WritingSubmissionMeta(
            part=2,
            part_label="Task 2",
            prompt_title="Opinion essay",
        ),
        queue_pending_count=0,
        created_at=datetime.now(UTC),
    )

    body = ApproveWritingRequest(
        human_criteria_scores=WritingHumanCriteriaScores(
            task_achievement=6.5,
            coherence=6.5,
            lexical_resource=6.0,
            grammar=7.0,
        ),
        reviewer_notes="Strong essay.",
    )

    with (
        patch("app.admin.writing.get_supabase", return_value=mock_client),
        patch("app.admin.writing.log_admin_action"),
        patch("app.admin.writing.get_writing_detail", return_value=detail),
        patch("app.cache.hybrid_cache.delete_many") as delete_many,
        patch(
            "app.cache.mock_cache.invalidate_mock_progress_caches"
        ) as invalidate_progress,
        patch(
            "app.cache.mock_cache.invalidate_mock_history_caches"
        ) as invalidate_history,
    ):
        result = approve_writing_review(
            review_id=REVIEW_ID,
            source="mock",
            body=body,
            admin_id=ADMIN_ID,
        )

    assert result.status == "completed"
    upsert_chain.upsert.assert_called_once()
    upsert_payload = upsert_chain.upsert.call_args[0][0]
    assert upsert_payload["module"] == "writing"
    assert upsert_payload["attempt_id"] == str(ATTEMPT_ID)
    delete_many.assert_called_once_with([f"dashboard_summary:{USER_ID}"])
    invalidate_progress.assert_called_once_with(
        user_id=USER_ID,
        mock_test_id=MOCK_TEST_ID,
        mock_attempt_id=MOCK_ATTEMPT_ID,
    )
    invalidate_history.assert_called_once_with(
        user_id=USER_ID,
        mock_test_id=MOCK_TEST_ID,
    )


def test_compute_overall_band_rounds_to_half():
    assert compute_overall_band(
        {
            "task_achievement": 6.5,
            "coherence": 6.5,
            "lexical_resource": 6.0,
            "grammar": 7.0,
        }
    ) == 6.5


def test_compute_overall_band_requires_four_criteria():
    with pytest.raises(ValueError):
        compute_overall_band({"task_achievement": 6.0, "coherence": 6.0})


def test_normalize_criteria_scores_partial_returns_none():
    assert normalize_criteria_scores({"task_achievement": 6.0}) is None


def test_ai_scores_to_criteria_maps_keys():
    scores = ai_scores_to_criteria(
        {
            "task_achievement": 6.5,
            "grammar": 6.0,
            "lexical_resource": 6.5,
            "coherence": 7.0,
        }
    )
    assert scores == {
        "task_achievement": 6.5,
        "coherence": 7.0,
        "lexical_resource": 6.5,
        "grammar": 6.0,
    }


def test_approve_request_requires_criteria():
    body = ApproveWritingRequest(
        human_criteria_scores=WritingHumanCriteriaScores(
            task_achievement=6.5,
            coherence=6.5,
            lexical_resource=6.0,
            grammar=7.0,
        ),
        reviewer_notes="Strong essay.",
    )
    assert body.reviewer_notes == "Strong essay."


def test_approve_request_rejects_out_of_range():
    with pytest.raises(ValidationError):
        ApproveWritingRequest(
            human_criteria_scores=WritingHumanCriteriaScores(
                task_achievement=6.5,
                coherence=6.5,
                lexical_resource=6.0,
                grammar=10.0,
            )
        )


def test_patch_request_accepts_draft_status():
    body = PatchWritingReviewRequest(
        status="in_review",
        human_criteria_scores=WritingHumanCriteriaScores(
            task_achievement=6.0,
            coherence=6.0,
            lexical_resource=6.0,
            grammar=6.0,
        ),
    )
    assert body.status == "in_review"


def test_writing_review_detail_schema_includes_evaluator_fields():
    now = datetime.now(UTC)
    detail = WritingReviewDetail(
        id=uuid4(),
        source="mock",
        attempt_id=uuid4(),
        status="pending",
        submission_meta=WritingSubmissionMeta(
            part=2,
            part_label="Task 2",
            prompt_title="Describe a skill you would like to learn.",
        ),
        student_target_band=7.0,
        student_current_band=6.0,
        queue_pending_count=4,
        created_at=now,
    )
    parsed = WritingReviewDetail.model_validate(detail.model_dump(mode="json"))
    assert parsed.submission_meta is not None
    assert parsed.submission_meta.part == 2
    assert parsed.queue_pending_count == 4
