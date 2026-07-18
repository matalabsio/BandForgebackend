"""Anthropic Claude client — direct API or Claude Platform on AWS."""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ClaudeAuthMode = Literal["direct", "aws"]


def _aws_base_url(region: str) -> str:
    return f"https://aws-external-anthropic.{region}.api.aws"


def _aws_messages_url(region: str) -> str:
    return f"{_aws_base_url(region)}/v1/messages"


def resolve_claude_auth_mode(settings: Settings | None = None) -> ClaudeAuthMode | None:
    """Return active Claude auth mode, or None if not configured."""
    s = settings or get_settings()
    mode = (s.anthropic_provider or "auto").strip().lower()
    has_direct = bool(s.anthropic_api_key.strip())
    has_aws = bool(s.anthropic_aws_api_key.strip()) and bool(
        s.anthropic_aws_workspace_id.strip()
    )

    if mode in ("direct", "anthropic"):
        return "direct" if has_direct else None
    if mode == "aws":
        return "aws" if has_aws else None
    if has_aws:
        return "aws"
    if has_direct:
        return "direct"
    return None


def claude_configured() -> bool:
    return resolve_claude_auth_mode() is not None


def claude_configuration_error() -> str | None:
    """Human-readable hint when Claude is not fully configured."""
    s = get_settings()
    mode = (s.anthropic_provider or "auto").strip().lower()
    has_aws_key = bool(s.anthropic_aws_api_key.strip())
    has_workspace = bool(s.anthropic_aws_workspace_id.strip())

    if mode in ("auto", "aws") and has_aws_key and not has_workspace:
        return (
            "ANTHROPIC_AWS_API_KEY is set but ANTHROPIC_AWS_WORKSPACE_ID is missing. "
            "Find it in AWS Console → Claude Platform on AWS → Workspaces, "
            "or run: python scripts/anthropic_aws_smoke.py --discover-workspaces"
        )
    if mode == "aws" and not has_aws_key:
        return "ANTHROPIC_PROVIDER=aws requires ANTHROPIC_AWS_API_KEY and ANTHROPIC_AWS_WORKSPACE_ID."
    if mode == "direct" and not s.anthropic_api_key.strip():
        return "ANTHROPIC_PROVIDER=direct requires ANTHROPIC_API_KEY."
    if resolve_claude_auth_mode() is None:
        return "Configure ANTHROPIC_AWS_API_KEY + ANTHROPIC_AWS_WORKSPACE_ID or ANTHROPIC_API_KEY."
    return None


async def discover_aws_workspaces(
    *,
    settings: Settings | None = None,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """List Claude Platform on AWS workspaces (control plane; no workspace header)."""
    s = settings or get_settings()
    api_key = s.anthropic_aws_api_key.strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_AWS_API_KEY is required to discover workspaces.")

    region = s.aws_region.strip() or "eu-north-1"
    url = f"{_aws_base_url(region)}/v1/organizations/workspaces"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            detail = response.text[:500]
            raise RuntimeError(
                f"Workspace discovery failed ({response.status_code}): {detail}"
            )
        data = response.json()

    workspaces = data.get("data") or []
    if not isinstance(workspaces, list):
        return []
    return [ws for ws in workspaces if isinstance(ws, dict)]


def _extract_message_text(data: dict[str, Any]) -> str:
    content_blocks = data.get("content") or []
    text_parts: list[str] = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
    content = "".join(text_parts).strip()
    if not content:
        raise RuntimeError("Claude returned no text content")
    return content


async def chat_completion_json(
    *,
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call Claude Messages API and return (content_text, raw_response)."""
    settings = get_settings()
    auth_mode = resolve_claude_auth_mode()
    if auth_mode is None:
        hint = claude_configuration_error() or "Claude is not configured"
        raise RuntimeError(hint)

    model_name = model or settings.anthropic_model
    request_timeout = (
        float(timeout)
        if timeout is not None
        else float(settings.speaking_eval_timeout_sec)
    )
    payload: dict[str, Any] = {
        "model": model_name,
        "max_tokens": max_tokens if max_tokens is not None else 4096,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "temperature": 0.2,
    }

    if auth_mode == "aws":
        url = _aws_messages_url(settings.aws_region.strip() or "eu-north-1")
        headers = {
            "x-api-key": settings.anthropic_aws_api_key.strip(),
            "anthropic-version": "2023-06-01",
            "anthropic-workspace-id": settings.anthropic_aws_workspace_id.strip(),
            "content-type": "application/json",
        }
    else:
        url = ANTHROPIC_MESSAGES_URL
        headers = {
            "x-api-key": settings.anthropic_api_key.strip(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    async with httpx.AsyncClient(timeout=request_timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            detail = response.text[:500]
            logger.error(
                "Claude %s request failed (%s): %s",
                auth_mode,
                response.status_code,
                detail,
            )
        response.raise_for_status()
        data = response.json()

    content = _extract_message_text(data)
    data["_bandforge_auth_mode"] = auth_mode
    return content, data
