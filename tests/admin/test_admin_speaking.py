"""Evaluator portal band math and schema tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.admin.schemas import (
    ApproveSpeakingRequest,
    HumanCriteriaScores,
    PatchSpeakingReviewRequest,
    ReopenSpeakingReviewRequest,
    SpeakingReviewDetail,
    SpeakingSubmissionMeta,
)
from app.admin.speaking import (
    _admin_evidence,
    _admin_pronunciation_advisory,
    _approval_request_hash,
    approve_speaking_review,
    reopen_speaking_review,
)
from app.admin.speaking_band import (
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
    result = MagicMock()
    result.data = data if data is not None else []
    result.count = count
    chain.execute.return_value = result
    return chain


def test_approve_speaking_review_invalidates_student_caches():
    existing_chain = _table_chain(
        [{
            "id": str(REVIEW_ID),
            "status": "pending",
            "attempt_id": str(ATTEMPT_ID),
            "audio_url": "speaking/audio.webm",
            "ai_scores": None,
        }]
    )
    responses_chain = _table_chain([{"id": str(uuid4()), "status": "confirmed"}])
    attempt_row_chain = _table_chain(
        [
            {
                "user_id": str(USER_ID),
                "mock_attempt_id": str(MOCK_ATTEMPT_ID),
                "mock_test_id": str(MOCK_TEST_ID),
            }
        ]
    )
    mock_client = MagicMock()
    rpc_result = MagicMock()
    rpc_result.data = {"applied": True, "attempt_id": str(ATTEMPT_ID), "version": 1}
    mock_client.rpc.return_value.execute.return_value = rpc_result

    def table_side_effect(name):
        if name == "speaking_reviews":
            return existing_chain
        if name == "speaking_responses":
            return responses_chain
        if name == "test_attempts":
            return attempt_row_chain
        return _table_chain()

    mock_client.table.side_effect = table_side_effect

    detail = SpeakingReviewDetail(
        id=REVIEW_ID,
        attempt_id=ATTEMPT_ID,
        status="completed",
        submission_meta=SpeakingSubmissionMeta(
            part=1,
            part_label="Part 1",
            prompt_title="Intro",
        ),
        queue_pending_count=0,
        created_at=datetime.now(UTC),
    )

    body = ApproveSpeakingRequest(
        human_criteria_scores=HumanCriteriaScores(
            fluency=6.5,
            lexical=6.5,
            grammar=6.0,
            pronunciation=7.0,
        ),
        reviewer_notes="Strong response.",
        audio_confirmed=True,
        confirmation="confirm_final_approval",
        idempotency_key="approval-key-0001",
    )

    with (
        patch("app.admin.speaking.get_supabase", return_value=mock_client),
        patch("app.admin.speaking.log_admin_action"),
        patch("app.admin.speaking.get_speaking_detail", return_value=detail),
        patch("app.cache.hybrid_cache.delete_many") as delete_many,
        patch(
            "app.cache.mock_cache.invalidate_mock_progress_caches"
        ) as invalidate_progress,
        patch(
            "app.cache.mock_cache.invalidate_mock_history_caches"
        ) as invalidate_history,
    ):
        result = approve_speaking_review(
            review_id=REVIEW_ID,
            body=body,
            admin_id=ADMIN_ID,
        )

    assert result.status == "completed"
    mock_client.rpc.assert_called_once()
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


def test_approve_speaking_review_requires_every_manifest_response():
    mock_client = MagicMock()
    review_chain = _table_chain(
        [
            {
                "id": str(REVIEW_ID),
                "status": "pending",
                "attempt_id": str(ATTEMPT_ID),
                "audio_url": None,
                "ai_scores": None,
            }
        ]
    )
    responses_chain = _table_chain(
        [{"id": str(uuid4()), "question_id": "q1", "status": "confirmed"}]
    )
    manifest_chain = _table_chain(
        [{"speaking_manifest": [{"id": "q1"}, {"id": "q2"}]}]
    )

    def table_side_effect(name):
        if name == "speaking_reviews":
            return review_chain
        if name == "speaking_responses":
            return responses_chain
        if name == "test_attempts":
            return manifest_chain
        return _table_chain()

    mock_client.table.side_effect = table_side_effect
    body = ApproveSpeakingRequest(
        human_criteria_scores=HumanCriteriaScores(
            fluency=6.5,
            lexical=6.5,
            grammar=6.0,
            pronunciation=7.0,
        ),
        reviewer_notes="Strong response.",
        audio_confirmed=True,
        confirmation="confirm_final_approval",
        idempotency_key="approval-key-0002",
    )

    with (
        patch("app.admin.speaking.get_supabase", return_value=mock_client),
        pytest.raises(HTTPException) as exc_info,
    ):
        approve_speaking_review(
            review_id=REVIEW_ID,
            body=body,
            admin_id=ADMIN_ID,
        )

    assert getattr(exc_info.value, "status_code", None) == 409
    mock_client.rpc.assert_not_called()


def test_approve_same_key_different_payload_conflicts():
    mock_client = MagicMock()
    mock_client.table.return_value = _table_chain(
        [
            {
                "id": str(REVIEW_ID),
                "status": "completed",
                "attempt_id": str(ATTEMPT_ID),
                "audio_url": "speaking/audio.webm",
                "ai_scores": None,
                "approval_idempotency_key": "approval-key-0003",
                "approval_request_hash": "different-hash",
            }
        ]
    )
    body = ApproveSpeakingRequest(
        human_criteria_scores=HumanCriteriaScores(
            fluency=6.5,
            lexical=6.5,
            grammar=6.0,
            pronunciation=7.0,
        ),
        reviewer_notes="Changed payload.",
        audio_confirmed=True,
        confirmation="confirm_final_approval",
        idempotency_key="approval-key-0003",
    )

    with (
        patch("app.admin.speaking.get_supabase", return_value=mock_client),
        pytest.raises(HTTPException) as exc_info,
    ):
        approve_speaking_review(
            review_id=REVIEW_ID,
            body=body,
            admin_id=ADMIN_ID,
        )

    assert exc_info.value.status_code == 409
    mock_client.rpc.assert_not_called()


def test_approve_same_key_same_payload_replays_successfully():
    body = ApproveSpeakingRequest(
        human_criteria_scores=HumanCriteriaScores(
            fluency=6.5,
            lexical=6.5,
            grammar=6.0,
            pronunciation=7.0,
        ),
        reviewer_notes="Unchanged payload.",
        audio_confirmed=True,
        confirmation="confirm_final_approval",
        idempotency_key="approval-key-0004",
    )
    mock_client = MagicMock()
    mock_client.table.return_value = _table_chain(
        [
            {
                "id": str(REVIEW_ID),
                "status": "completed",
                "attempt_id": str(ATTEMPT_ID),
                "audio_url": "speaking/audio.webm",
                "ai_scores": None,
                "approval_idempotency_key": body.idempotency_key,
                "approval_request_hash": _approval_request_hash(body),
            }
        ]
    )
    detail = SpeakingReviewDetail(
        id=REVIEW_ID,
        attempt_id=ATTEMPT_ID,
        status="completed",
        queue_pending_count=0,
        created_at=datetime.now(UTC),
    )

    with (
        patch("app.admin.speaking.get_supabase", return_value=mock_client),
        patch("app.admin.speaking.get_speaking_detail", return_value=detail),
        patch("app.admin.speaking._invalidate_speaking_result_caches") as invalidate,
    ):
        result = approve_speaking_review(
            review_id=REVIEW_ID,
            body=body,
            admin_id=ADMIN_ID,
        )

    assert result.status == "completed"
    mock_client.rpc.assert_not_called()
    invalidate.assert_called_once_with(mock_client, str(ATTEMPT_ID))


def test_reopen_invalidates_student_and_mock_caches():
    mock_client = MagicMock()
    review_chain = _table_chain([{"attempt_id": str(ATTEMPT_ID)}])
    attempt_chain = _table_chain(
        [
            {
                "user_id": str(USER_ID),
                "mock_attempt_id": str(MOCK_ATTEMPT_ID),
                "mock_test_id": str(MOCK_TEST_ID),
            }
        ]
    )
    mock_client.table.side_effect = lambda name: (
        review_chain if name == "speaking_reviews" else attempt_chain
    )
    rpc_result = MagicMock()
    rpc_result.data = [{"id": str(REVIEW_ID), "status": "in_review"}]
    mock_client.rpc.return_value.execute.return_value = rpc_result
    detail = SpeakingReviewDetail(
        id=REVIEW_ID,
        attempt_id=ATTEMPT_ID,
        status="in_review",
        queue_pending_count=0,
        created_at=datetime.now(UTC),
    )

    with (
        patch("app.admin.speaking.get_supabase", return_value=mock_client),
        patch("app.admin.speaking.get_speaking_detail", return_value=detail),
        patch("app.cache.hybrid_cache.delete_many") as delete_many,
        patch(
            "app.cache.mock_cache.invalidate_mock_progress_caches"
        ) as invalidate_progress,
        patch(
            "app.cache.mock_cache.invalidate_mock_history_caches"
        ) as invalidate_history,
    ):
        result = reopen_speaking_review(
            review_id=REVIEW_ID,
            body=ReopenSpeakingReviewRequest(reason="Examiner correction required."),
            admin_id=ADMIN_ID,
        )

    assert result.status == "in_review"
    delete_many.assert_called_once_with([f"dashboard_summary:{USER_ID}"])
    invalidate_progress.assert_called_once()
    invalidate_history.assert_called_once()


def test_compute_overall_band_rounds_to_half():
    assert compute_overall_band(
        {"fluency": 6.5, "lexical": 6.5, "grammar": 6.0, "pronunciation": 7.0}
    ) == 6.5
    assert compute_overall_band(
        {"fluency": 6.0, "lexical": 6.0, "grammar": 6.0, "pronunciation": 6.25}
    ) == 6.0


def test_compute_overall_band_requires_four_criteria():
    with pytest.raises(ValueError):
        compute_overall_band({"fluency": 6.0, "lexical": 6.0})


def test_normalize_criteria_scores_partial_returns_none():
    assert normalize_criteria_scores({"fluency": 6.0}) is None


def test_ai_scores_to_criteria_maps_keys():
    scores = ai_scores_to_criteria(
        {"fluency": 6.5, "grammar": 6.0, "lexical": 6.5, "pronunciation": 7.0}
    )
    assert scores == {
        "fluency": 6.5,
        "lexical": 6.5,
        "grammar": 6.0,
        "pronunciation": 7.0,
    }


def test_approve_request_requires_criteria():
    body = ApproveSpeakingRequest(
        human_criteria_scores=HumanCriteriaScores(
            fluency=6.5,
            lexical=6.5,
            grammar=6.0,
            pronunciation=7.0,
        ),
        reviewer_notes="Strong response.",
        audio_confirmed=True,
        confirmation="confirm_final_approval",
        idempotency_key="approval-key-0001",
    )
    assert body.reviewer_notes == "Strong response."


def test_approve_request_rejects_incomplete_criteria():
    with pytest.raises(ValidationError):
        ApproveSpeakingRequest(
            human_criteria_scores=HumanCriteriaScores(
                fluency=6.5,
                lexical=6.5,
                grammar=6.0,
                pronunciation=10.0,
            )
        )


def test_patch_request_accepts_draft_status():
    body = PatchSpeakingReviewRequest(
        status="in_review",
        human_criteria_scores=HumanCriteriaScores(
            fluency=6.0,
            lexical=6.0,
            grammar=6.0,
            pronunciation=6.0,
        ),
    )
    assert body.status == "in_review"


def test_ai_scores_to_criteria_from_phase_c_payload():
    payload = {
        "fluency": 6.5,
        "lexical": 6.0,
        "grammar": 5.5,
        "pronunciation": 6.5,
        "status": "ai_complete",
        "evaluation": {
            "band_scores": {
                "FC": 6.5,
                "LR": 6.0,
                "GRA": 5.5,
                "P": 6.5,
                "overall": 6.0,
            }
        },
    }
    criteria = ai_scores_to_criteria(payload)
    assert criteria == {
        "fluency": 6.5,
        "lexical": 6.0,
        "grammar": 5.5,
        "pronunciation": 6.5,
    }


def test_speaking_review_detail_schema_includes_evaluator_fields():
    now = datetime.now(UTC)
    detail = SpeakingReviewDetail(
        id=uuid4(),
        attempt_id=uuid4(),
        status="pending",
        submission_meta=SpeakingSubmissionMeta(
            part=2,
            part_label="Part 2",
            prompt_title="Describe a skill you would like to learn.",
        ),
        student_target_band=7.0,
        student_current_band=6.0,
        queue_pending_count=4,
        created_at=now,
    )
    parsed = SpeakingReviewDetail.model_validate(detail.model_dump(mode="json"))
    assert parsed.submission_meta is not None
    assert parsed.submission_meta.part == 2
    assert parsed.queue_pending_count == 4


def test_admin_evidence_keeps_rich_ids_and_marks_pronunciation_advisory():
    evaluation = {
        "band_scores": {"P_confidence": 0.55},
        "evidence_quotes": [
            {
                "response_id": "response-1",
                "question_id": "question-1",
                "part": 3,
                "quote": "a grounded quote",
                "criterion": "P",
                "polarity": "weakness",
                "issue": "Clarity",
                "title": "Unclear phrase",
                "explanation": "The transcript suggests a possible clarity issue.",
                "suggestion": "Confirm by listening to the recording.",
            }
        ],
    }

    evidence = _admin_evidence(evaluation)
    assert evidence[0]["response_id"] == "response-1"
    assert evidence[0]["question_id"] == "question-1"
    assert evidence[0]["issue"] == "Clarity"
    assert evidence[0]["title"] == "Unclear phrase"
    assert evidence[0]["explanation"]
    assert evidence[0]["suggestion"]
    assert evidence[0]["advisory_only"] is True
    assert evidence[0]["inference_source"] == "transcript_inferred"
    assert evidence[0]["confidence"] == 0.55

    advisory = _admin_pronunciation_advisory(evaluation)
    assert advisory == {
        "inference_source": "transcript_inferred",
        "advisory_only": True,
        "confidence": 0.55,
        "low_confidence": True,
        "released_score_authority": "human_examiner",
    }
