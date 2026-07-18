"""Stub writing evaluation provider for offline development."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.diagnostic.evaluation_schemas import build_stub_evaluation
from app.writing.providers.constants import PROVIDER_NAME_STUB, WRITING_STUB_DELAY_SEC


class StubWritingProvider:
    """Returns schema-valid JSON after a short delay — never calls an LLM."""

    name = PROVIDER_NAME_STUB

    def __init__(self, *, task_part: int = 2, essay: str = "") -> None:
        self._task_part = task_part
        self._essay = essay

    @property
    def model(self) -> str:
        return PROVIDER_NAME_STUB

    def configured(self) -> bool:
        return True

    async def chat_json(self, *, system: str, user: str) -> tuple[str, dict[str, Any]]:
        del system, user  # prompts unused — deterministic stub
        await asyncio.sleep(WRITING_STUB_DELAY_SEC)
        evaluation = build_stub_evaluation(task_part=self._task_part, essay=self._essay)
        content = json.dumps(evaluation.model_dump())
        raw: dict[str, Any] = {
            "stub": True,
            "model": self.model,
            "content": content,
        }
        return content, raw
