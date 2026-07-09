"""OpenAI Whisper transcription client."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"


def whisper_configured() -> bool:
    return bool(get_settings().openai_api_key.strip())


async def transcribe_audio(
    *,
    audio_bytes: bytes,
    filename: str = "recording.webm",
) -> dict[str, Any]:
    """Transcribe audio via OpenAI Whisper. Returns {text, words}."""
    settings = get_settings()
    api_key = settings.openai_api_key.strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    model = settings.openai_whisper_model or "whisper-1"
    timeout = float(settings.speaking_eval_timeout_sec)

    headers = {"Authorization": f"Bearer {api_key}"}
    files = {"file": (filename, audio_bytes)}
    data = {
        "model": model,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
        "language": "en",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            OPENAI_TRANSCRIPTIONS_URL,
            headers=headers,
            files=files,
            data=data,
        )
        response.raise_for_status()
        payload = response.json()

    text = str(payload.get("text") or "").strip()
    words_raw = payload.get("words") or []
    words: list[dict[str, Any]] = []
    for w in words_raw:
        if not isinstance(w, dict):
            continue
        word = str(w.get("word") or "").strip()
        if not word:
            continue
        try:
            words.append(
                {
                    "word": word,
                    "start": float(w.get("start", 0)),
                    "end": float(w.get("end", 0)),
                }
            )
        except (TypeError, ValueError):
            continue

    return {"text": text, "words": words, "raw": payload}
