"""Deterministic fluency metrics from Whisper word timestamps."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, TypedDict

FLUENCY_METRICS_VERSION = "response-weighted-v1"


class FluencyMetrics(TypedDict):
    words_per_minute: float
    total_speaking_seconds: float
    long_pauses: int
    response_count: int
    questions_asked: int
    word_count: int


def long_pause_markers(
    words: list[dict[str, Any]],
    *,
    threshold_sec: float = 2.0,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Compact pause markers from consecutive word gaps (> threshold_sec)."""
    if len(words) < 2:
        return []
    markers: list[dict[str, Any]] = []
    for prev, nxt in zip(words, words[1:]):
        try:
            gap = float(nxt["start"]) - float(prev["end"])
            after_word = str(prev.get("word") or "").strip()
        except (KeyError, TypeError, ValueError):
            continue
        if gap <= threshold_sec or not after_word:
            continue
        markers.append(
            {
                "after_word": after_word,
                "gap_sec": round(gap, 1),
            }
        )
        if len(markers) >= limit:
            break
    return markers


def long_pauses(words: list[dict[str, Any]], threshold_sec: float = 2.0) -> int:
    """Count gaps between consecutive words longer than threshold_sec."""
    if len(words) < 2:
        return 0
    count = 0
    for prev, nxt in zip(words, words[1:]):
        try:
            gap = float(nxt["start"]) - float(prev["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if gap > threshold_sec:
            count += 1
    return count


def total_speaking_seconds_from_words(
    words: list[dict[str, Any]],
    *,
    fallback_sec: float | None = None,
) -> float:
    if not words:
        return float(fallback_sec or 0)
    try:
        start = float(words[0]["start"])
        end = float(words[-1]["end"])
        duration = max(0.0, end - start)
        if duration > 0:
            return duration
    except (KeyError, TypeError, ValueError):
        pass
    return float(fallback_sec or 0)


def words_per_minute(word_count: int, total_seconds: float) -> float:
    if total_seconds <= 0 or word_count <= 0:
        return 0.0
    return round(word_count / (total_seconds / 60.0), 1)


def compute_fluency_metrics(
    *,
    words: list[dict[str, Any]],
    duration_sec: int | None = None,
    response_count: int = 1,
    questions_asked: int = 1,
) -> FluencyMetrics:
    """Compute per-part fluency metrics from Whisper word timestamps."""
    fallback = float(duration_sec) if duration_sec and duration_sec > 0 else None
    total_seconds = total_speaking_seconds_from_words(words, fallback_sec=fallback)
    word_count = len(words)
    return {
        "words_per_minute": words_per_minute(word_count, total_seconds),
        "total_speaking_seconds": round(total_seconds, 1),
        "long_pauses": long_pauses(words),
        "response_count": max(0, response_count),
        "questions_asked": max(0, questions_asked),
        "word_count": word_count,
    }


def aggregate_fluency_metrics(
    responses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate response snapshots without creating cross-response pauses."""
    ordered = sorted(
        responses,
        key=lambda item: (
            int(item.get("sequence_number") or 0),
            str(item.get("response_id") or item.get("id") or ""),
        ),
    )
    part_buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for response in ordered:
        part_buckets[int(response.get("part") or 1)].append(response)

    def combine(items: list[dict[str, Any]]) -> dict[str, Any]:
        word_count = 0
        seconds = 0.0
        pauses = 0
        for item in items:
            metrics = item.get("fluency_metrics")
            if not isinstance(metrics, dict):
                continue
            word_count += int(metrics.get("word_count") or 0)
            seconds += float(metrics.get("total_speaking_seconds") or 0)
            pauses += int(metrics.get("long_pauses") or 0)
        return {
            "words_per_minute": words_per_minute(word_count, seconds),
            "total_speaking_seconds": round(seconds, 1),
            "long_pauses": pauses,
            "response_count": len(items),
            "questions_asked": len(items),
            "word_count": word_count,
        }

    response_metrics = [
        {
            "response_id": str(item.get("response_id") or item.get("id") or ""),
            "part": int(item.get("part") or 1),
            "sequence_number": int(item.get("sequence_number") or 0),
            **(
                item["fluency_metrics"]
                if isinstance(item.get("fluency_metrics"), dict)
                else compute_fluency_metrics(
                    words=[],
                    duration_sec=None,
                    response_count=1,
                    questions_asked=1,
                )
            ),
        }
        for item in ordered
    ]
    sources = [
        {
            "response_id": str(item.get("response_id") or item.get("id") or ""),
            "checksum": str(
                item.get("metrics_source_checksum")
                or item.get("content_sha256")
                or ""
            ),
            "provider": str(item.get("transcription_provider") or ""),
            "model": str(item.get("transcription_model") or ""),
        }
        for item in ordered
    ]
    source_checksum = hashlib.sha256(
        json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "version": FLUENCY_METRICS_VERSION,
        "source_checksum": source_checksum,
        "source_checksums": sources,
        "response_metrics": response_metrics,
        "part_metrics": {
            str(part): combine(items)
            for part, items in sorted(part_buckets.items())
        },
        "attempt_metrics": combine(ordered),
    }
