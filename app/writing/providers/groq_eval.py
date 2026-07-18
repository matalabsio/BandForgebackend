"""Groq provider for writing evaluation."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.diagnostic.groq_client import chat_completion_json, groq_configured
from app.writing.providers.constants import PROVIDER_NAME_GROQ


class GroqWritingProvider:
    name = PROVIDER_NAME_GROQ

    @property
    def model(self) -> str:
        return get_settings().groq_model

    def configured(self) -> bool:
        return groq_configured()

    async def chat_json(self, *, system: str, user: str) -> tuple[str, dict[str, Any]]:
        return await chat_completion_json(
            system=system,
            user=user,
            model=self.model,
        )
