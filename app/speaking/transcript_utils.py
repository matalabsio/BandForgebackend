"""Meaningful-speech helpers for Speaking ASR transcripts and fluency metrics."""

from __future__ import annotations

import re
from typing import Any

MIN_MEANINGFUL_WORDS_ATTEMPT = 8
MIN_MEANINGFUL_WORDS_RESPONSE = 3

PUNCT_ONLY = re.compile(r"^[\W_]+$", re.UNICODE)
_WORD_TOKEN = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


def is_meaningful_word_token(token: str) -> bool:
    """True when token contains at least one alphanumeric character."""
    raw = (token or "").strip()
    if not raw or PUNCT_ONLY.match(raw):
        return False
    return bool(_WORD_TOKEN.search(raw))


def meaningful_word_count(transcript: str) -> int:
    """Count tokens with alphanumeric content (punctuation-only → 0)."""
    text = (transcript or "").strip()
    if not text:
        return 0
    return sum(1 for part in text.split() if is_meaningful_word_token(part))


def is_meaningful_transcript(
    transcript: str,
    *,
    min_words: int = MIN_MEANINGFUL_WORDS_RESPONSE,
) -> bool:
    return meaningful_word_count(transcript) >= max(1, min_words)


def filter_meaningful_whisper_words(
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop Whisper tokens that are punctuation-only noise."""
    filtered: list[dict[str, Any]] = []
    for item in words:
        if not isinstance(item, dict):
            continue
        token = str(item.get("word") or "").strip()
        if not is_meaningful_word_token(token):
            continue
        filtered.append(item)
    return filtered


def attempt_meaningful_word_count(responses: list[dict[str, Any]]) -> int:
    """Sum meaningful words across response dicts (transcript field)."""
    total = 0
    for row in responses:
        transcript = str(row.get("transcript") or "")
        total += meaningful_word_count(transcript)
    return total


def is_sufficient_attempt_speech(responses: list[dict[str, Any]]) -> bool:
    return attempt_meaningful_word_count(responses) >= MIN_MEANINGFUL_WORDS_ATTEMPT


INSUFFICIENT_SPEECH_MESSAGE = (
    "We couldn't detect enough speech to score this attempt."
)
