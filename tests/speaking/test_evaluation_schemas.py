"""Tests for locked Speaking evaluation schema."""

import pytest
from pydantic import ValidationError

from app.speaking.evaluation_schemas import (
    SpeakingEvaluation,
    build_stub_evaluation,
    evaluation_to_admin_criteria,
    validate_quotes_in_transcript,
)


def test_build_stub_evaluation_validates():
    transcript = "I come from a small city and enjoy living there."
    ev = build_stub_evaluation(transcript=transcript, part=1)
    validate_quotes_in_transcript(ev, transcript)
    criteria = evaluation_to_admin_criteria(ev)
    assert criteria["fluency"] == ev.band_scores.FC
    assert criteria["lexical"] == ev.band_scores.LR


def test_validate_quotes_rejects_non_substring():
    transcript = "Hello world"
    ev = build_stub_evaluation(transcript=transcript, part=1)
    ev.evidence_quotes[0].quote = "not in transcript"
    with pytest.raises(ValueError):
        validate_quotes_in_transcript(ev, transcript)


def test_band_scores_round_to_half():
    from app.speaking.evaluation_schemas import BandScores

    bs = BandScores(FC=6.3, LR=6.3, GRA=6.3, P=6.3, P_confidence=0.5, overall=6.3)
    assert bs.FC == 6.5
