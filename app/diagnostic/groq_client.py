"""Thin Groq chat-completions client (OpenAI-compatible API)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

GROQ_TIMEOUT_SEC = 60.0


async def chat_completion_json(
    *,
    system: str,
    user: str,
    model: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call Groq and return (content_text, raw_response_dict)."""
    settings = get_settings()
    api_key = settings.groq_api_key.strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")

    model_name = model or settings.groq_model
    base = settings.groq_api_base.rstrip("/")
    url = f"{base}/chat/completions"

    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=GROQ_TIMEOUT_SEC) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Groq returned no choices")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Groq returned empty content")

    return content.strip(), data
