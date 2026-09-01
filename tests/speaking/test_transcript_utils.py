"""Unit tests for speaking transcript_utils."""

from app.speaking.transcript_utils import (
    MIN_MEANINGFUL_WORDS_ATTEMPT,
    attempt_meaningful_word_count,
    filter_meaningful_whisper_words,
    is_meaningful_transcript,
    is_meaningful_word_token,
    is_sufficient_attempt_speech,
    meaningful_word_count,
)


def test_meaningful_word_count_punctuation_only():
    assert meaningful_word_count(".") == 0
    assert meaningful_word_count("..") == 0
    assert meaningful_word_count("—") == 0


def test_meaningful_word_count_short_real_words():
    assert meaningful_word_count("I") == 1
    assert meaningful_word_count("I am from India") == 4


def test_is_meaningful_transcript():
    assert not is_meaningful_transcript(".", min_words=3)
    assert is_meaningful_transcript("I am from India", min_words=3)


def test_filter_meaningful_whisper_words():
    words = [
        {"word": ".", "start": 0.0, "end": 0.2},
        {"word": "I", "start": 0.3, "end": 0.5},
        {"word": "..", "start": 0.6, "end": 0.8},
        {"word": "am", "start": 0.9, "end": 1.1},
    ]
    filtered = filter_meaningful_whisper_words(words)
    assert [w["word"] for w in filtered] == ["I", "am"]


def test_attempt_meaningful_word_count():
    responses = [
        {"transcript": "."},
        {"transcript": "I"},
        {"transcript": "am fine"},
    ]
    assert attempt_meaningful_word_count(responses) == 3


def test_is_sufficient_attempt_speech():
    low = [{"transcript": "I"} for _ in range(4)]
    assert attempt_meaningful_word_count(low) < MIN_MEANINGFUL_WORDS_ATTEMPT
    assert not is_sufficient_attempt_speech(low)

    ok = [{"transcript": "I am from India and I like it here"}]
    assert is_sufficient_attempt_speech(ok)


def test_is_meaningful_word_token():
    assert not is_meaningful_word_token(".")
    assert is_meaningful_word_token("I")
    assert is_meaningful_word_token("don't")


def test_build_insufficient_speech_scores():
    from app.speaking.evaluation_schemas import build_insufficient_speech_scores

    scores = build_insufficient_speech_scores(
        metrics={
            "attempt_metrics": {
                "words_per_minute": 25.0,
                "total_speaking_seconds": 9.6,
                "word_count": 4,
            }
        },
        fingerprint="fp-1",
        meaningful_word_count=2,
    )
    assert scores["status"] == "insufficient_speech"
    assert scores["ai_band"] is None
    assert scores["evaluation"]["strengths"] == []
    assert scores["attempt_metrics"]["words_per_minute"] == 25.0
    assert scores["attempt_metrics"]["meaningful_word_count"] == 2
