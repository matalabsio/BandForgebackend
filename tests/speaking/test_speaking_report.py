"""Student speaking report API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.speaking.evaluation_schemas import build_stub_evaluation
from app.speaking.service import get_speaking_report

ATTEMPT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
REVIEW_ID = UUID("11111111-1111-4111-8111-111111111111")

STUB_TRANSCRIPT = (
    "I live in a small city near the coast and I enjoy walking by the sea on weekends. "
    "My hometown has changed a lot in the last ten years."
)


def _attempt_row() -> dict:
    return {
        "id": str(ATTEMPT_ID),
        "user_id": str(USER_ID),
        "module": "speaking",
        "part": 1,
        "status": "completed",
        "completed_at": datetime.now(UTC).isoformat(),
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
    assert report.fluency_metrics.words_per_minute == 110.0
    assert report.fluency == 6.0
    assert report.ai_status == "ai_stub"
    assert report.student_name == "Test Student"
    assert report.reviewer_notes == "Clear answers overall."


def test_get_speaking_report_exposes_pause_markers_from_words():
    row = _review_row(human_band=6.5)
    row["ai_scores"]["words"] = [
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
        patch("app.speaking.service.generate_signed_url", return_value=None),
    ):
        report = get_speaking_report(attempt_id=ATTEMPT_ID, user_id=USER_ID)

    assert report.overall_band == 7.0
    assert report.evaluation is None
    assert report.fluency == 6.0


def test_build_stub_evaluation_has_report_fields():
    ev = build_stub_evaluation(transcript=STUB_TRANSCRIPT, part=1)
    assert len(ev.evidence_quotes) >= 4
    assert ev.next_band_advice
    assert ev.vocabulary_highlights
    assert ev.part_performance
    assert 0.0 <= ev.band_scores.P_confidence <= 1.0
