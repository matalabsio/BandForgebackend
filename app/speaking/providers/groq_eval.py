"""Groq LLM evaluation provider."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.diagnostic.groq_client import chat_completion_json, groq_configured
from app.speaking.evaluation_schemas import SpeakingEvaluation
from app.speaking.providers.constants import PROVIDER_NAME_GROQ
from app.speaking.providers.evaluation_call import call_evaluation_with_retry


class GroqEvaluationProvider:
    name = PROVIDER_NAME_GROQ

    @property
    def model(self) -> str:
        return get_settings().groq_model

    def configured(self) -> bool:
        return groq_configured()

    async def evaluate(
        self,
        *,
        transcript: str,
        fluency_metrics: dict[str, Any],
        prompts: list[str],
        part: int,
    ) -> SpeakingEvaluation:
        settings = get_settings()

        async def llm_call(system: str, user: str) -> tuple[str, dict]:
            return await chat_completion_json(
                system=system,
                user=user,
                model=settings.groq_model,
            )

        return await call_evaluation_with_retry(
            llm_call=llm_call,
            transcript=transcript,
            fluency_metrics=fluency_metrics,
            prompts=prompts,
            part=part,
            provider_label="Groq",
        )
