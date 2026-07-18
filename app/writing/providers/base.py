"""Protocol for writing evaluation LLM providers."""

from __future__ import annotations

from typing import Protocol


class WritingEvaluationProvider(Protocol):
    name: str

    @property
    def model(self) -> str: ...

    def configured(self) -> bool: ...

    async def chat_json(self, *, system: str, user: str) -> tuple[str, dict]: ...
