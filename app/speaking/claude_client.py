"""Anthropic Claude client for Speaking evaluation JSON."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def claude_configured() -> bool:
    return bool(get_settings().anthropic_api_key.strip())


async def chat_completion_json(
    *,
    system: str,
    user: str,
    model: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call Claude Messages API and return (content_text, raw_response)."""
    settings = get_settings()
    api_key = settings.anthropic_api_key.strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    model_name = model or settings.anthropic_model
    timeout = float(settings.speaking_eval_timeout_sec)

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model_name,
        "max_tokens": 4096,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            ANTHROPIC_MESSAGES_URL,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    content_blocks = data.get("content") or []
    text_parts: list[str] = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
    content = "".join(text_parts).strip()
    if not content:
        raise RuntimeError("Claude returned no text content")
    return content, data
