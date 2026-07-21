"""Unit tests for speaking fluency metrics."""

from app.speaking.fluency_metrics import (
    aggregate_fluency_metrics,
    compute_fluency_metrics,
    long_pauses,
    total_speaking_seconds_from_words,
    words_per_minute,
)


def test_long_pauses_counts_gaps_over_threshold():
    words = [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 3.0, "end": 3.5},
        {"word": "c", "start": 3.6, "end": 4.0},
    ]
    assert long_pauses(words, threshold_sec=2.0) == 1


def test_total_speaking_seconds_from_words():
    words = [
        {"word": "hi", "start": 1.0, "end": 1.5},
        {"word": "there", "start": 1.6, "end": 2.0},
    ]
    assert total_speaking_seconds_from_words(words) == 1.0


def test_total_speaking_seconds_fallback():
    assert total_speaking_seconds_from_words([], fallback_sec=42) == 42.0


def test_words_per_minute():
    assert words_per_minute(120, 60) == 120.0
    assert words_per_minute(0, 60) == 0.0


def test_compute_fluency_metrics():
    words = [
        {"word": f"w{i}", "start": float(i), "end": float(i) + 0.4}
        for i in range(10)
    ]
    metrics = compute_fluency_metrics(
        words=words,
        duration_sec=10,
        response_count=1,
        questions_asked=4,
    )
    assert metrics["response_count"] == 1
    assert metrics["questions_asked"] == 4
    assert metrics["words_per_minute"] > 0
    assert metrics["total_speaking_seconds"] > 0


def _response(
    response_id: str,
    *,
    part: int,
    sequence: int,
    words: int,
    seconds: float,
    pauses: int,
) -> dict:
    return {
        "id": response_id,
        "part": part,
        "sequence_number": sequence,
        "content_sha256": response_id.rjust(64, "0"),
        "transcription_provider": "groq_whisper",
        "transcription_model": "whisper-large-v3-turbo",
        "fluency_metrics": {
            "word_count": words,
            "total_speaking_seconds": seconds,
            "long_pauses": pauses,
            "words_per_minute": 0,
            "response_count": 1,
            "questions_asked": 1,
        },
    }


def test_weighted_attempt_and_part_metrics_use_total_words_over_total_time():
    snapshot = aggregate_fluency_metrics(
        [
            _response("1", part=1, sequence=1, words=30, seconds=30, pauses=1),
            _response("2", part=1, sequence=2, words=30, seconds=10, pauses=2),
            _response("3", part=2, sequence=3, words=60, seconds=60, pauses=3),
        ]
    )
    assert snapshot["part_metrics"]["1"]["words_per_minute"] == 90.0
    assert snapshot["attempt_metrics"]["words_per_minute"] == 72.0
    assert snapshot["attempt_metrics"]["long_pauses"] == 6


def test_empty_response_is_represented_without_division_error():
    snapshot = aggregate_fluency_metrics(
        [_response("1", part=1, sequence=1, words=0, seconds=0, pauses=0)]
    )
    assert snapshot["attempt_metrics"]["words_per_minute"] == 0.0
    assert snapshot["attempt_metrics"]["response_count"] == 1


def test_aggregation_never_creates_inter_response_pauses():
    snapshot = aggregate_fluency_metrics(
        [
            _response("1", part=1, sequence=1, words=1, seconds=1, pauses=0),
            _response("2", part=1, sequence=2, words=1, seconds=1, pauses=0),
        ]
    )
    assert snapshot["attempt_metrics"]["long_pauses"] == 0


def test_response_metrics_and_checksum_are_stable_in_sequence_order():
    first = _response("1", part=1, sequence=1, words=10, seconds=5, pauses=0)
    second = _response("2", part=2, sequence=2, words=20, seconds=10, pauses=0)
    ordered = aggregate_fluency_metrics([first, second])
    reversed_input = aggregate_fluency_metrics([second, first])
    assert ordered["response_metrics"] == reversed_input["response_metrics"]
    assert ordered["source_checksum"] == reversed_input["source_checksum"]
