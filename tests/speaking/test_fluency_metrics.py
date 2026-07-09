"""Unit tests for speaking fluency metrics."""

from app.speaking.fluency_metrics import (
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
