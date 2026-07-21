"""Phase 7 — review comparison, audit history, analytics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from app.admin.audit_routes import get_review_history, _summary_for_action
from app.admin.review_analytics import get_review_analytics
from app.admin.review_comparison import (
    approve_audit_metadata,
    is_overridden,
    mae,
)
from app.admin.schemas import (
    ApproveSpeakingRequest,
    HumanCriteriaScores,
    SpeakingReviewDetail,
)
from app.admin.speaking import approve_speaking_review


REVIEW_ID = UUID("11111111-1111-4111-8111-111111111111")
ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ADMIN_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


def _table_chain(data=None, count=None):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
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


def test_is_overridden_when_criterion_diff_at_least_half():
    assert is_overridden(
        human_criteria={"fluency": 7.0, "lexical": 6.0, "grammar": 6.0, "pronunciation": 6.0},
        ai_criteria={"fluency": 6.0, "lexical": 6.0, "grammar": 6.0, "pronunciation": 6.0},
        human_overall=6.5,
        ai_overall=6.0,
    )
    assert not is_overridden(
        human_criteria={"fluency": 6.0, "lexical": 6.0, "grammar": 6.0, "pronunciation": 6.0},
        ai_criteria={"fluency": 6.0, "lexical": 6.0, "grammar": 6.0, "pronunciation": 6.0},
        human_overall=6.0,
        ai_overall=6.0,
    )


def test_approve_audit_metadata_snapshot():
    meta = approve_audit_metadata(
        human_band=7.0,
        human_criteria={"fluency": 7.0, "lexical": 7.0, "grammar": 7.0, "pronunciation": 7.0},
        ai_band=6.0,
        ai_criteria={"fluency": 6.0, "lexical": 6.0, "grammar": 6.0, "pronunciation": 6.0},
        extra={"source": "mock"},
    )
    assert meta["human_band"] == 7.0
    assert meta["ai_band"] == 6.0
    assert meta["ai_criteria"]["fluency"] == 6.0
    assert meta["overridden"] is True
    assert meta["delta_overall"] == 1.0
    assert meta["source"] == "mock"


def test_mae_average():
    assert mae([0.5, -0.5, 1.0]) == 0.667
    assert mae([]) is None


def test_summary_for_approve_action():
    assert "overridden" in _summary_for_action(
        "speaking.approve",
        {"delta_overall": -0.5, "overridden": True},
    )
    assert "Saved draft" in _summary_for_action("writing.draft", {"status": "in_review"})


def test_approve_speaking_logs_ai_snapshot():
    existing_chain = _table_chain(
        [
            {
                "id": str(REVIEW_ID),
                "status": "pending",
                "attempt_id": str(ATTEMPT_ID),
                "audio_url": "speaking/audio.webm",
                "ai_scores": {
                    "fluency": 6.0,
                    "lexical": 6.0,
                    "grammar": 6.0,
                    "pronunciation": 6.0,
                },
            }
        ]
    )
    attempt_row_chain = _table_chain([])
    responses_chain = _table_chain([{"id": str(uuid4()), "status": "confirmed"}])

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
        queue_pending_count=0,
        created_at=datetime.now(UTC),
    )
    body = ApproveSpeakingRequest(
        human_criteria_scores=HumanCriteriaScores(
            fluency=7.0,
            lexical=7.0,
            grammar=7.0,
            pronunciation=7.0,
        ),
        audio_confirmed=True,
        confirmation="confirm_final_approval",
        idempotency_key="approval-key-0001",
        ai_override_note="Recording supports the higher human score.",
    )

    with (
        patch("app.admin.speaking.get_supabase", return_value=mock_client),
        patch("app.admin.speaking.get_speaking_detail", return_value=detail),
    ):
        approve_speaking_review(review_id=REVIEW_ID, body=body, admin_id=ADMIN_ID)

    meta = mock_client.rpc.call_args.args[1]["p_audit_metadata"]
    assert meta["ai_band"] == 6.0
    assert meta["human_band"] == 7.0
    assert meta["overridden"] is True
    assert meta["delta_overall"] == 1.0
    assert meta["ai_criteria"]["fluency"] == 6.0


def test_get_review_history_maps_timeline():
    log_id = uuid4()
    chain = _table_chain(
        [
            {
                "id": str(log_id),
                "action": "speaking.approve",
                "metadata": {
                    "delta_overall": -0.5,
                    "overridden": True,
                    "human_band": 6.0,
                },
                "created_at": datetime.now(UTC).isoformat(),
                "users": {"email": "trainer@example.com"},
            }
        ]
    )
    mock_client = MagicMock()
    mock_client.table.return_value = chain

    with patch("app.admin.audit_routes.get_supabase", return_value=mock_client):
        history = get_review_history(
            resource_type="speaking_review",
            resource_id=REVIEW_ID,
            actions=["speaking.draft", "speaking.approve"],
        )

    assert len(history.items) == 1
    assert history.items[0].admin_email == "trainer@example.com"
    assert "Approved" in history.items[0].summary
    assert "overridden" in history.items[0].summary
    chain.eq.assert_any_call("resource_id", str(REVIEW_ID))


def test_review_analytics_aggregates_fixture_rows():
    now = datetime.now(UTC)
    speaking_rows = [
        {
            "id": str(uuid4()),
            "status": "completed",
            "human_band": 6.5,
            "human_criteria_scores": {
                "fluency": 6.5,
                "lexical": 6.5,
                "grammar": 6.5,
                "pronunciation": 6.5,
            },
            "ai_scores": {
                "fluency": 6.0,
                "lexical": 6.0,
                "grammar": 6.0,
                "pronunciation": 6.0,
            },
            "reviewed_at": now.isoformat(),
        },
        {
            "id": str(uuid4()),
            "status": "completed",
            "human_band": 6.0,
            "human_criteria_scores": {
                "fluency": 6.0,
                "lexical": 6.0,
                "grammar": 6.0,
                "pronunciation": 6.0,
            },
            "ai_scores": {
                "fluency": 6.0,
                "lexical": 6.0,
                "grammar": 6.0,
                "pronunciation": 6.0,
            },
            "reviewed_at": now.isoformat(),
        },
        {
            "id": str(uuid4()),
            "status": "completed",
            "human_band": 7.0,
            "human_criteria_scores": {
                "fluency": 7.0,
                "lexical": 7.0,
                "grammar": 7.0,
                "pronunciation": 7.0,
            },
            "ai_scores": None,
            "reviewed_at": now.isoformat(),
        },
    ]

    writing_chain = _table_chain([])
    speaking_chain = _table_chain(speaking_rows)

    mock_client = MagicMock()

    def table_side_effect(name):
        if name == "speaking_reviews":
            return speaking_chain
        return writing_chain

    mock_client.table.side_effect = table_side_effect

    with patch("app.admin.review_analytics.get_supabase", return_value=mock_client):
        analytics = get_review_analytics(module="speaking", days=30)

    assert analytics.completed == 3
    assert analytics.with_ai == 2
    assert analytics.without_ai == 1
    assert analytics.agreement_rate == 1.0  # both with-AI overall within 0.5
    assert analytics.override_rate == 0.5  # first row criterion/Δ ≥ 0.5
    assert analytics.overall_mae is not None
    assert len(analytics.criterion_mae) == 4
