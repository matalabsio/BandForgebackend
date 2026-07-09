"""Groq Whisper ASR provider."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.diagnostic.groq_client import groq_configured
from app.speaking.providers.base import TranscriptionResult
from app.speaking.providers.constants import PROVIDER_NAME_GROQ_WHISPER

logger = logging.getLogger(__name__)


def _parse_words(payload: dict[str, Any]) -> list[dict[str, float | str]]:
    words_raw = payload.get("words") or []
    words: list[dict[str, float | str]] = []
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
    return words


class GroqWhisperProvider:
    name = PROVIDER_NAME_GROQ_WHISPER

    @property
    def model(self) -> str:
        return get_settings().groq_whisper_model or "whisper-large-v3-turbo"

    def configured(self) -> bool:
        return groq_configured()

    async def transcribe(
        self, *, audio_bytes: bytes, filename: str
    ) -> TranscriptionResult:
        settings = get_settings()
        api_key = settings.groq_api_key.strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not configured")

        base = settings.groq_api_base.rstrip("/")
        url = f"{base}/audio/transcriptions"
        timeout = float(settings.speaking_eval_timeout_sec)

        headers = {"Authorization": f"Bearer {api_key}"}
        files = {"file": (filename, audio_bytes)}
        data = {
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
            "language": "en",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url, headers=headers, files=files, data=data
            )
            response.raise_for_status()
            payload = response.json()

        text = str(payload.get("text") or "").strip()
        return TranscriptionResult(text=text, words=_parse_words(payload))
