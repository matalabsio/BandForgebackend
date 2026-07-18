"""Provider protocols for Speaking ASR and evaluation."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict

from app.speaking.evaluation_schemas import SpeakingEvaluation


class TranscriptionResult(TypedDict):
    text: str
    words: list[dict[str, float | str]]


class ASRProvider(Protocol):
    name: str
    model: str

    def configured(self) -> bool: ...

    async def transcribe(
        self, *, audio_bytes: bytes, filename: str
    ) -> TranscriptionResult: ...


class EvaluationProvider(Protocol):
    name: str
    model: str

    def configured(self) -> bool: ...

    async def evaluate(
        self,
        *,
        transcript: str,
        fluency_metrics: dict[str, Any],
        prompts: list[str],
        part: int,
    ) -> SpeakingEvaluation: ...
