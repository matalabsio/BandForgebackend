"""Student speaking report API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.speaking.evaluation_schemas import build_stub_evaluation
from app.speaking.service import (
    get_pending_status,
    get_speaking_report,
    resolve_release_state,
)

ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
REVIEW_ID = UUID("11111111-1111-4111-8111-111111111111")
MOCK_ID = UUID("22222222-2222-4222-8222-222222222222")
QUESTION_ID = UUID("33333333-3333-4333-8333-333333333333")
RESPONSE_ID = UUID("44444444-4444-4444-8444-444444444444")

STUB_TRANSCRIPT = (
    "I live in a small city near the coast and I enjoy walking by the sea on weekends. "
    "My hometown has changed a lot in the last ten years."
)


def _attempt_row() -> dict:
    return {
        "id": str(ATTEMPT_ID),
        "user_id": str(USER_ID),
        "mock_test_id": str(MOCK_ID),
        "module": "speaking",
        "part": 1,
        "status": "completed",
        "completed_at": datetime.now(UTC).isoformat(),
        "mock_tests": {"title": "IELTS Academic Mock 1", "catalog_number": 1},
        "speaking_manifest": [
            {
                "id": str(QUESTION_ID),
                "question_number": 1,
                "question_type": "speaking_part1",
                "prompt": "Where are you from?",
                "part": 1,
                "sequence_number": 1,
                "kind": "question",
                "prep_seconds": 0,
                "max_recording_seconds": 45,
            }
        ],
    }


def _response_row() -> dict:
    return {
        "id": str(RESPONSE_ID),
        "attempt_id": str(ATTEMPT_ID),
        "question_id": str(QUESTION_ID),
        "part": 1,
        "sequence_number": 1,
        "duration_sec": 42,
        "status": "confirmed",
        "audio_url": "speaking/test/part-1/recording.webm",
        "transcription_status": "completed",
        "transcript": STUB_TRANSCRIPT,
        "transcript_words": [],
        "fluency_metrics": {
            "words_per_minute": 110.0,
            "total_speaking_seconds": 42.0,
            "long_pauses": 2,
            "response_count": 1,
            "questions_asked": 1,
            "word_count": 24,
        },
    }


def _review_row(*, human_band: float | None, with_eval: bool = True) -> dict:
    evaluation = None
    fluency_metrics = {
        "words_per_minute": 110.0,
        "total_speaking_seconds": 42.0,
        "long_pauses": 2,
        "response_count": 1,
        "questions_asked": 1,
    }
    ai_scores: dict = {
        "status": "ai_stub",
        "ai_band": 6.0,
        "fluency": 6.0,
        "lexical": 6.0,
        "grammar": 5.5,
        "pronunciation": 6.0,
        "fluency_metrics": fluency_metrics,
        "provider_asr": "stub",
        "provider_eval": "stub",
        "prompt_version": "v1-stub",
    }
    if with_eval:
        evaluation = build_stub_evaluation(transcript=STUB_TRANSCRIPT, part=1)
        ai_scores["evaluation"] = evaluation.model_dump()
    return {
        "id": str(REVIEW_ID),
        "attempt_id": str(ATTEMPT_ID),
        "status": "completed" if human_band is not None else "pending",
        "human_band": human_band,
        "human_criteria_scores": (
            {
                "fluency": 6.5,
                "lexical": 6.0,
                "grammar": 6.0,
                "pronunciation": 6.5,
            }
            if human_band is not None
            else None
        ),
        "ai_scores": ai_scores,
        "submission_meta": {"part": 1},
        "reviewer_notes": "Clear answers overall.",
        "reviewer_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
        "reviewer_email": "private@example.com",
        "reviewer_display_name": "Dr. A. Examiner",
        "reviewer_credential_label": "Certified IELTS Examiner",
        "released_at": "2026-07-21T06:30:00Z",
        "approval_version": 2,
        "student_display_name_at_release": "Snapshot Student",
        "student_target_band_at_release": 7.0,
        "transcript": STUB_TRANSCRIPT,
        "audio_url": "speaking/test/part-1/recording.webm",
        "created_at": datetime.now(UTC).isoformat(),
    }


def test_get_speaking_report_requires_human_band():
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt_row()),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=_review_row(human_band=None),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            get_speaking_report(
                attempt_id=ATTEMPT_ID,
                user_id=USER_ID,
                student_name="Test Student",
            )
        assert exc.value.status_code == 409


def test_get_speaking_report_returns_evaluation_and_metrics():
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt_row()),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=_review_row(human_band=6.5),
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=[_response_row()],
        ),
        patch(
            "app.speaking.service.generate_signed_url",
            return_value="https://cdn.example/audio.webm",
        ),
    ):
        report = get_speaking_report(
            attempt_id=ATTEMPT_ID,
            user_id=USER_ID,
            student_name="Test Student",
        )

    assert report.overall_band == 6.5
    assert report.human_verified is True
    assert report.human_criteria_scores is not None
    assert report.human_criteria_scores.fluency == 6.5
    assert report.transcript == STUB_TRANSCRIPT
    assert report.audio_play_url == "https://cdn.example/audio.webm"
    assert report.evaluation is not None
    assert report.evaluation["band_scores"]["overall"] == 6.0
    assert report.evaluation["next_band_advice"]
    assert report.fluency_metrics is not None
    # Canonical WPM is recomputed from the released response's word count/duration,
    # rather than trusting the deliberately inconsistent review snapshot.
    assert report.fluency_metrics.words_per_minute == 34.3
    assert report.attempt_metrics == report.fluency_metrics
    assert report.fluency_summary.overall == report.attempt_metrics
    assert report.fluency_summary.source == "response_metrics"
    assert report.fluency_summary.complete is True
    assert report.part_metrics["1"].words_per_minute == 34.3
    assert report.fluency == 6.0
    assert report.ai_status == "ai_stub"
    assert report.student_name == "Snapshot Student"
    assert report.reviewer_notes == "Clear answers overall."
    assert report.release_state == "released"
    assert report.report_available is True
    assert report.approval_version == 2
    assert report.reviewer is not None
    assert report.reviewer.model_dump() == {
        "display_name": "Dr. A. Examiner",
        "credential_label": "Certified IELTS Examiner",
    }
    serialized = report.model_dump(mode="json")
    assert "reviewer_id" not in str(serialized)
    assert "private@example.com" not in str(serialized)


def test_released_legacy_attempt_without_manifest_returns_degraded_report():
    attempt = _attempt_row()
    attempt["speaking_manifest"] = None
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=_review_row(human_band=6.5),
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=[],
        ),
    ):
        report = get_speaking_report(
            attempt_id=ATTEMPT_ID,
            user_id=USER_ID,
            student_name="Test Student",
        )

    assert report.schema_version == "speaking-report.v2"
    assert report.report_available is True
    assert report.responses == []
    assert report.analysis.status == "degraded"
    assert "responses" in report.analysis.unavailable_sections


def test_get_speaking_report_exposes_pause_markers_from_words():
    row = _review_row(human_band=6.5)
    response = _response_row()
    response["transcript_words"] = [
        {"word": "I", "start": 0.0, "end": 0.2},
        {"word": "live", "start": 0.25, "end": 0.5},
        {"word": "near", "start": 3.0, "end": 3.3},
        {"word": "the", "start": 3.4, "end": 3.5},
        {"word": "sea", "start": 3.6, "end": 3.9},
    ]
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt_row()),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=row,
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=[response],
        ),
        patch("app.speaking.service.generate_signed_url", return_value=None),
    ):
        report = get_speaking_report(attempt_id=ATTEMPT_ID, user_id=USER_ID)

    assert len(report.pause_markers) >= 1
    assert report.pause_markers[0].after_word == "live"
    assert report.pause_markers[0].gap_sec >= 2.0


def test_long_pause_markers_helper():
    from app.speaking.fluency_metrics import long_pause_markers

    markers = long_pause_markers(
        [
            {"word": "hello", "start": 0.0, "end": 0.3},
            {"word": "world", "start": 2.8, "end": 3.1},
        ]
    )
    assert markers == [{"after_word": "hello", "gap_sec": 2.5}]


def test_get_speaking_report_without_evaluation_still_works():
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt_row()),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=_review_row(human_band=7.0, with_eval=False),
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=[_response_row()],
        ),
        patch("app.speaking.service.generate_signed_url", return_value=None),
    ):
        report = get_speaking_report(attempt_id=ATTEMPT_ID, user_id=USER_ID)

    assert report.overall_band == 7.0
    assert report.evaluation is None
    assert report.fluency == 6.0


def test_release_state_transitions_and_ai_failure_release():
    attempt = _attempt_row()
    pending = _review_row(human_band=None)
    pending["evaluation_status"] = "processing"
    assert resolve_release_state(
        attempt=attempt,
        review=pending,
        transcription_progress={"total": 1, "completed": 0, "failed": 0},
    ).release_state == "processing"

    pending["evaluation_status"] = "failed"
    assert resolve_release_state(
        attempt=attempt,
        review=pending,
        transcription_progress={"total": 1, "completed": 0, "failed": 1},
    ).release_state == "awaiting_examiner"

    pending["reopened_at"] = "2026-07-21T07:00:00Z"
    assert resolve_release_state(
        attempt=attempt, review=pending
    ).release_state == "withdrawn"

    released = _review_row(human_band=6.5)
    released["evaluation_status"] = "failed"
    state = resolve_release_state(
        attempt=attempt,
        review=released,
        transcription_progress={"total": 1, "completed": 0, "failed": 1},
    )
    assert state.release_state == "released"
    assert state.report_available is True


def test_report_gate_requires_all_four_valid_human_criteria():
    row = _review_row(human_band=6.5)
    row["human_criteria_scores"].pop("pronunciation")
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt_row()),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=row,
        ),
        pytest.raises(HTTPException) as exc,
    ):
        get_speaking_report(attempt_id=ATTEMPT_ID, user_id=USER_ID)
    assert exc.value.status_code == 409


def test_pending_response_exposes_release_contract():
    row = _review_row(human_band=None)
    row["evaluation_status"] = "failed"
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt_row()),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=row,
        ),
        patch(
            "app.speaking.service.repo.transcription_progress",
            return_value={"total": 1, "completed": 0, "failed": 1},
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=[_response_row()],
        ),
    ):
        pending = get_pending_status(attempt_id=ATTEMPT_ID, user_id=USER_ID)

    assert pending.release_state == "awaiting_examiner"
    assert pending.report_available is False
    assert pending.reviewer is None
    assert len(pending.responses) == 1
    assert pending.responses[0].transcript == STUB_TRANSCRIPT
    assert pending.responses[0].prompt == "Where are you from?"


def test_pending_response_returns_all_transcripts_in_manifest_sequence():
    question_two = UUID("55555555-5555-4555-8555-555555555555")
    response_two = UUID("66666666-6666-4666-8666-666666666666")
    attempt = _attempt_row()
    attempt["speaking_manifest"].append(
        {
            "id": str(question_two),
            "question_number": 2,
            "question_type": "speaking_part2",
            "prompt": "Describe a skill you learned.",
            "part": 2,
            "sequence_number": 2,
            "kind": "question",
            "prep_seconds": 60,
            "max_recording_seconds": 120,
        }
    )
    first = {
        **_response_row(),
        "transcription_status": "failed",
        "transcript": "",
        "transcription_error": "provider credentials must not leak",
    }
    second_transcript = "First paragraph.\n\nSecond paragraph remains exact."
    second = {
        **_response_row(),
        "id": str(response_two),
        "question_id": str(question_two),
        "part": 2,
        "sequence_number": 2,
        "duration_sec": 91,
        "transcription_status": "completed",
        "transcript": second_transcript,
    }
    review = _review_row(human_band=None)
    review["evaluation_status"] = "completed"

    with (
        patch("app.speaking.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=review,
        ),
        patch(
            "app.speaking.service.repo.transcription_progress",
            return_value={"total": 2, "completed": 1, "failed": 1},
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=[second, first],
        ),
    ):
        pending = get_pending_status(attempt_id=ATTEMPT_ID, user_id=USER_ID)

    assert [item.sequence for item in pending.responses] == [1, 2]
    assert [item.part for item in pending.responses] == [1, 2]
    assert pending.responses[0].transcription_status == "failed"
    assert pending.responses[0].transcription_error == (
        "Transcription unavailable after retry."
    )
    assert "credentials" not in (pending.responses[0].transcription_error or "")
    assert pending.responses[1].prompt == "Describe a skill you learned."
    assert pending.responses[1].transcript == second_transcript


def test_pending_response_enforces_attempt_ownership_before_loading_transcripts():
    attempt = _attempt_row()
    attempt["user_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt"
        ) as get_review,
        patch("app.speaking.service.repo.list_speaking_responses") as list_responses,
        pytest.raises(HTTPException) as exc,
    ):
        get_pending_status(attempt_id=ATTEMPT_ID, user_id=USER_ID)

    assert exc.value.status_code == 404
    get_review.assert_not_called()
    list_responses.assert_not_called()


def test_report_enforces_attempt_ownership():
    attempt = _attempt_row()
    attempt["user_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt"
        ) as get_review,
        pytest.raises(HTTPException) as exc,
    ):
        get_speaking_report(attempt_id=ATTEMPT_ID, user_id=USER_ID)

    assert exc.value.status_code == 404
    get_review.assert_not_called()


def test_build_stub_evaluation_has_report_fields():
    ev = build_stub_evaluation(transcript=STUB_TRANSCRIPT, part=1)
    assert len(ev.evidence_quotes) >= 4
    assert ev.next_band_advice
    assert ev.vocabulary_highlights
    assert ev.part_performance
    assert 0.0 <= ev.band_scores.P_confidence <= 1.0


def _complete_attempt_and_responses() -> tuple[dict, list[dict]]:
    parts = [1, 1, 1, 1, 2, 3, 3, 3]
    attempt = _attempt_row()
    manifest: list[dict] = []
    responses: list[dict] = []
    for sequence, part in enumerate(parts, start=1):
        question_id = UUID(f"50000000-0000-4000-8000-{sequence:012d}")
        response_id = UUID(f"60000000-0000-4000-8000-{sequence:012d}")
        prompt = f"Frozen prompt {sequence}"
        transcript = (
            "I really really value continuous learning."
            if sequence == 1
            else f"This is the unique answer number {sequence}."
        )
        manifest.append(
            {
                "id": str(question_id),
                "question_number": sequence,
                "question_type": f"speaking_part{part}",
                "prompt": prompt,
                "part": part,
                "sequence_number": sequence,
                "kind": "question",
                "prep_seconds": 60 if part == 2 else 0,
                "max_recording_seconds": 120 if part == 2 else 60,
            }
        )
        words = []
        if sequence == 1:
            words = [
                {"word": "I", "start": 0.0, "end": 0.1},
                {"word": "really", "start": 0.2, "end": 0.5},
                {"word": "really", "start": 2.8, "end": 3.1},
                {"word": "value", "start": 3.2, "end": 3.5},
                {"word": "continuous", "start": 3.6, "end": 4.0},
                {"word": "learning", "start": 4.1, "end": 4.5},
            ]
        responses.append(
            {
                "id": str(response_id),
                "attempt_id": str(ATTEMPT_ID),
                "question_id": str(question_id),
                "part": part,
                "sequence_number": sequence,
                "duration_sec": 30 + sequence,
                "status": "confirmed",
                "audio_url": f"private/raw-{sequence}.webm",
                "transcript": transcript,
                "transcript_words": words,
                "fluency_metrics": {
                    "words_per_minute": 100 + sequence,
                    "total_speaking_seconds": 20,
                    "long_pauses": 1 if sequence == 1 else 0,
                    "response_count": 1,
                    "questions_asked": 1,
                    "word_count": len(words),
                },
                "transcription_provider": "private-provider",
                "transcription_error": "private-error",
                "content_sha256": "f" * 64,
            }
        )
    attempt["speaking_manifest"] = manifest
    return attempt, list(reversed(responses))


def test_v2_complete_report_order_grounding_timing_and_privacy():
    attempt, responses = _complete_attempt_and_responses()
    review = _review_row(human_band=6.5)
    evaluation = build_stub_evaluation(transcript=STUB_TRANSCRIPT, part=1).model_dump()
    evaluation["part_performance"] = [
        {"part": 1, "note": "Clear short answers.", "band_estimate": 6.0},
        {"part": 2, "note": "Sustained response.", "band_estimate": 6.5},
        {"part": 3, "note": "Developed discussion.", "band_estimate": 6.5},
    ]
    evaluation["evidence_quotes"] = [
        {
            "quote": "continuous learning",
            "criterion": "LR",
            "polarity": "strength",
            "part": 1,
            "response_id": responses[-1]["id"],
            "question_id": responses[-1]["question_id"],
            "issue": "Range",
            "title": "Relevant vocabulary",
            "explanation": "Uses a precise topic phrase.",
            "suggestion": "Keep using precise phrases.",
        },
        {
            "quote": "really",
            "criterion": "FC",
            "polarity": "weakness",
            "part": 1,
            "response_id": responses[-1]["id"],
            "question_id": responses[-1]["question_id"],
            "issue": "Repetition",
            "title": "Repeated intensifier",
            "explanation": "The intensifier is repeated.",
            "suggestion": "Pause instead of repeating.",
        },
        {
            "quote": "unique answer number 5",
            "criterion": "GRA",
            "polarity": "strength",
            "part": 2,
            "response_id": responses[3]["id"],
            "question_id": responses[3]["question_id"],
            "issue": "Structure",
            "title": "Complete clause",
            "explanation": "The response uses a complete clause.",
            "suggestion": "Extend it with a reason.",
        },
        {
            "quote": "unique answer number 8",
            "criterion": "P",
            "polarity": "strength",
            "part": 3,
            "response_id": responses[0]["id"],
            "question_id": responses[0]["question_id"],
            "issue": "Clarity",
            "title": "Clear delivery",
            "explanation": "The phrase is intelligible.",
            "suggestion": "Maintain the same clarity.",
        },
    ]
    evaluation["recurring_patterns"] = [
        {
            "pattern": "Repeats an intensifier",
            "criterion": "FC",
            "frequency": "sometimes",
            "examples": ["really"],
        }
    ]
    review["ai_scores"]["evaluation"] = evaluation
    review["ai_scores"]["part_metrics"] = {
        str(part): {
            "words_per_minute": 100 + part,
            "total_speaking_seconds": 40,
            "long_pauses": part,
            "response_count": [4, 1, 3][part - 1],
            "questions_asked": [4, 1, 3][part - 1],
            "word_count": 20,
        }
        for part in (1, 2, 3)
    }

    with (
        patch("app.speaking.service.repo.get_attempt", return_value=attempt),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=review,
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=responses,
        ),
        patch(
            "app.speaking.service.generate_signed_url",
            side_effect=lambda key, expiry: f"https://signed.example/{key}?ttl={expiry}",
        ) as signer,
    ):
        report = get_speaking_report(attempt_id=ATTEMPT_ID, user_id=USER_ID)

    assert report.schema_version == "speaking-report.v2"
    assert [item.sequence for item in report.responses] == list(range(1, 9))
    assert [item.prompt for item in report.responses] == [
        f"Frozen prompt {index}" for index in range(1, 9)
    ]
    assert [len(part.response_ids) for part in report.parts] == [4, 1, 3]
    assert [part.part for part in report.parts] == [1, 2, 3]
    assert [part.label for part in report.parts] == [
        "Introduction and Interview",
        "Long Turn",
        "Discussion",
    ]
    assert report.parts[1].metrics is not None
    assert report.parts[1].metrics.response_count == 1
    assert signer.call_count == 8
    assert all(call.kwargs["expiry"] == 3600 for call in signer.call_args_list)
    assert all(item.audio_expires_at is not None for item in report.responses)
    assert report.responses[0].transcript_words[1].start_ms == 200
    assert report.responses[0].pause_markers[0].duration_ms == 2300
    assert len(report.evidence) == 4
    unique = next(item for item in report.evidence if item.quote == "continuous learning")
    repeated = next(item for item in report.evidence if item.quote == "really")
    assert unique.span is not None
    assert unique.span.start_ms == 3600
    assert repeated.span is None
    assert report.patterns[0].occurrence_count == 2
    assert (
        report.patterns[0].occurrence_count_semantics
        == "grounded_example_matches"
    )
    assert report.patterns[0].frequency_is_model_estimate is True
    assert report.patterns[0].examples[0].response_id == report.responses[0].id
    assert report.fluency_summary.source == "response_metrics"
    assert report.fluency_summary.complete is True
    assert report.fluency_summary.overall is not None
    assert report.fluency_summary.overall.response_count == 8
    assert len(report.fluency_summary.responses) == 8
    pronunciation = next(item for item in report.evidence if item.criterion == "P")
    assert pronunciation.advisory_only is True
    assert pronunciation.inference_source == "transcript_inferred"
    assert pronunciation.confidence == 0.6
    assert report.pronunciation_advisory.score_authority == "human_examiner"
    assert report.pronunciation_advisory.ai_advisory_only is True
    assert report.pronunciation_advisory.ai_low_confidence is True
    assert report.student.display_name == "Snapshot Student"
    assert report.student.target_band_at_release == 7.0
    assert report.scores.criteria["grammar"].target_gap == 1.0
    assert report.scores.biggest_gap is not None
    assert report.analysis.status == "complete"

    serialized = report.model_dump(mode="json")
    rendered = str(serialized)
    for forbidden in (
        "private-provider",
        "private-error",
        "content_sha256",
        "provider_asr",
        "provider_eval",
        "model_asr",
        "metrics_source_checksum",
        "reviewer_flags",
        "reviewer_id",
        "reviewer_email",
        "user_id",
    ):
        assert forbidden not in rendered


def test_v2_marks_analysis_degraded_without_valid_evaluation():
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt_row()),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=_review_row(human_band=7.0, with_eval=False),
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=[_response_row()],
        ),
        patch("app.speaking.service.generate_signed_url", return_value=None),
    ):
        report = get_speaking_report(attempt_id=ATTEMPT_ID, user_id=USER_ID)

    assert report.analysis.status == "degraded"
    assert "evidence" in report.analysis.unavailable_sections
    assert report.evidence == []
    assert report.patterns == []


def test_v2_pattern_without_grounded_example_has_no_exact_count():
    review = _review_row(human_band=6.5)
    evaluation = review["ai_scores"]["evaluation"]
    evaluation["recurring_patterns"] = [
        {
            "pattern": "Uses fillers",
            "criterion": "FC",
            "frequency": "often",
            "examples": ["invented filler"],
        }
    ]
    with (
        patch("app.speaking.service.repo.get_attempt", return_value=_attempt_row()),
        patch(
            "app.speaking.service.repo.get_speaking_review_for_attempt",
            return_value=review,
        ),
        patch(
            "app.speaking.service.repo.list_speaking_responses",
            return_value=[_response_row()],
        ),
        patch("app.speaking.service.generate_signed_url", return_value=None),
    ):
        report = get_speaking_report(attempt_id=ATTEMPT_ID, user_id=USER_ID)

    pattern = report.patterns[0]
    assert pattern.occurrence_count is None
    assert pattern.occurrence_count_semantics is None
    assert pattern.examples == []
    assert pattern.frequency_is_model_estimate is True


def test_v2_snapshot_migration_is_atomic_and_removes_direct_response_access():
    migration = (
        Path(__file__).parents[2]
        / "supabase/migrations/20260721126000_speaking_report_v2_snapshots.sql"
    ).read_text()
    assert "student_display_name_at_release = v_student_display_name" in migration
    assert "student_target_band_at_release = v_student_target_band" in migration
    assert "DROP POLICY IF EXISTS speaking_responses_select_own" in migration
    assert "REVOKE ALL ON TABLE speaking_responses FROM anon, authenticated" in migration
