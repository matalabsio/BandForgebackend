"""OpenAI Whisper ASR provider."""

from __future__ import annotations

from app.config import get_settings
from app.speaking.providers.base import TranscriptionResult
from app.speaking.providers.constants import PROVIDER_NAME_OPENAI_WHISPER
from app.speaking.whisper_client import transcribe_audio, whisper_configured


class OpenAIWhisperProvider:
    name = PROVIDER_NAME_OPENAI_WHISPER

    @property
    def model(self) -> str:
        return get_settings().openai_whisper_model or "whisper-1"

    def configured(self) -> bool:
        return whisper_configured()

    async def transcribe(
        self, *, audio_bytes: bytes, filename: str
    ) -> TranscriptionResult:
        result = await transcribe_audio(audio_bytes=audio_bytes, filename=filename)
        return TranscriptionResult(
            text=str(result.get("text") or ""),
            words=list(result.get("words") or []),
        )
