"""Resend and Meta WhatsApp Cloud API adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class DeliveryResult:
    provider_message_id: str


class ResendProvider:
    def __init__(self, *, api_key: str, sender: str):
        self.api_key = api_key
        self.sender = sender

    async def send(
        self, *, to: str, subject: str, html: str, idempotency_key: str
    ) -> DeliveryResult:
        if not self.api_key:
            raise ProviderError("email provider is not configured", retryable=False)
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Idempotency-Key": idempotency_key,
                    },
                    json={
                        "from": self.sender,
                        "to": [to],
                        "subject": subject,
                        "html": html,
                    },
                )
            except httpx.HTTPError as exc:
                raise ProviderError("email provider request failed") from exc
        if response.status_code >= 400:
            raise ProviderError(
                f"email provider returned HTTP {response.status_code}",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        message_id = str(response.json().get("id") or "")
        if not message_id:
            raise ProviderError("email provider returned no message id")
        return DeliveryResult(message_id)


class MetaWhatsAppProvider:
    def __init__(
        self,
        *,
        graph_version: str,
        phone_number_id: str,
        access_token: str,
        template_name: str,
        template_language: str,
    ):
        self.graph_version = graph_version.strip("/")
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.template_name = template_name
        self.template_language = template_language

    async def send(
        self, *, to: str, components: list[dict[str, Any]]
    ) -> DeliveryResult:
        if not all(
            (
                self.graph_version,
                self.phone_number_id,
                self.access_token,
                self.template_name,
                self.template_language,
            )
        ):
            raise ProviderError("WhatsApp provider is not configured", retryable=False)
        url = (
            f"https://graph.facebook.com/{self.graph_version}/"
            f"{self.phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": self.template_name,
                "language": {"code": self.template_language},
                "components": components,
            },
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.HTTPError as exc:
                raise ProviderError("WhatsApp provider request failed") from exc
        if response.status_code >= 400:
            raise ProviderError(
                f"WhatsApp provider returned HTTP {response.status_code}",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        messages = response.json().get("messages") or []
        message_id = str(messages[0].get("id") or "") if messages else ""
        if not message_id:
            raise ProviderError("WhatsApp provider returned no message id")
        return DeliveryResult(message_id)
