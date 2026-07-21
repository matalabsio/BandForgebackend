"""Anthropic Claude evaluation provider."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.speaking.claude_client import chat_completion_json, claude_configured
from app.speaking.evaluation_schemas import SpeakingEvaluation
from app.speaking.providers.constants import PROVIDER_NAME_ANTHROPIC_CLAUDE
from app.speaking.providers.evaluation_call import call_evaluation_with_retry


class ClaudeEvaluationProvider:
    name = PROVIDER_NAME_ANTHROPIC_CLAUDE

    @property
    def model(self) -> str:
        return get_settings().anthropic_model

    def configured(self) -> bool:
        return claude_configured()

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
                model=settings.anthropic_model,
            )

        return await call_evaluation_with_retry(
            llm_call=llm_call,
            transcript=transcript,
            fluency_metrics=fluency_metrics,
            prompts=prompts,
            part=part,
            provider_label="Claude",
        )

    async def evaluate_attempt(
        self,
        *,
        responses: list[dict[str, Any]],
        fluency_metrics: dict[str, Any],
    ) -> SpeakingEvaluation:
        settings = get_settings()

        async def llm_call(system: str, user: str) -> tuple[str, dict]:
            return await chat_completion_json(
                system=system, user=user, model=settings.anthropic_model
            )

        return await call_evaluation_with_retry(
            llm_call=llm_call,
            transcript="\n\n".join(str(item["transcript"]) for item in responses),
            fluency_metrics=fluency_metrics,
            prompts=[str(item.get("prompt") or "") for item in responses],
            part=int(responses[0]["part"]),
            provider_label="Claude",
            responses=responses,
        )
