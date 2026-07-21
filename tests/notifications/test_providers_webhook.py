import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.notifications.providers import MetaWhatsAppProvider, ResendProvider
from app.notifications.repository import record_delivery_event
from app.notifications.templates import speaking_release_email_html, speaking_report_url
from app.notifications.webhook import process_payload, verify_challenge, verify_signature


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, response):
        self.post = AsyncMock(return_value=response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def test_release_email_escapes_every_user_value_and_has_no_scores():
    html = speaking_release_email_html(
        student_name="<script>alert(1)</script>",
        examiner_name='Dr "Exam" <x>',
        report_url='https://app.example/report?a="x"&b=1',
    )
    assert "<script>" not in html
    assert "<x>" not in html
    assert "&quot;x&quot;" in html
    assert "score" not in html.lower()
    assert "transcript" not in html.lower()
    assert speaking_report_url("https://app.example", "a/b", 3) == (
        "https://app.example/test/3/speaking/results?attempt=a%2Fb"
    )


def test_resend_returns_provider_message_id_and_idempotency_header():
    client = _Client(_Response({"id": "email-123"}))
    with patch("app.notifications.providers.httpx.AsyncClient", return_value=client):
        result = asyncio.run(
            ResendProvider(api_key="key", sender="from@example.com").send(
                to="to@example.com",
                subject="Ready",
                html="<p>Ready</p>",
                idempotency_key="job-1",
            )
        )
    assert result.provider_message_id == "email-123"
    assert client.post.call_args.kwargs["headers"]["Idempotency-Key"] == "job-1"


def test_meta_payload_uses_configured_template_without_sensitive_content():
    client = _Client(_Response({"messages": [{"id": "wamid.123"}]}))
    provider = MetaWhatsAppProvider(
        graph_version="v23.0",
        phone_number_id="phone-id",
        access_token="secret",
        template_name="speaking_ready",
        template_language="en",
    )
    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Student"},
                {"type": "text", "text": "https://app/report/1"},
            ],
        }
    ]
    with patch("app.notifications.providers.httpx.AsyncClient", return_value=client):
        result = asyncio.run(provider.send(to="+919999999999", components=components))
    request = client.post.call_args
    assert request.args[0].endswith("/v23.0/phone-id/messages")
    assert request.kwargs["json"]["template"]["name"] == "speaking_ready"
    assert "score" not in json.dumps(request.kwargs["json"]).lower()
    assert result.provider_message_id == "wamid.123"


def test_meta_challenge_signature_and_status_deduplication():
    settings = SimpleNamespace(
        meta_whatsapp_verify_token="verify-me",
        meta_whatsapp_app_secret="app-secret",
    )
    with patch("app.notifications.webhook.get_settings", return_value=settings):
        assert (
            verify_challenge(
                mode="subscribe", token="verify-me", challenge="challenge-value"
            )
            == "challenge-value"
        )
        with pytest.raises(HTTPException):
            verify_challenge(mode="subscribe", token="wrong", challenge="x")
        raw = b'{"object":"whatsapp_business_account"}'
        signature = "sha256=" + hmac.new(
            b"app-secret", raw, hashlib.sha256
        ).hexdigest()
        verify_signature(raw, signature)
        with pytest.raises(HTTPException):
            verify_signature(raw, "sha256=bad")

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {"id": "wamid.1", "status": "delivered", "timestamp": "1"}
                            ]
                        }
                    }
                ]
            }
        ]
    }
    with patch(
        "app.notifications.webhook.repository.record_delivery_event",
        side_effect=[True, False],
    ) as record:
        assert process_payload(payload) == 1
        assert process_payload(payload) == 0
    assert record.call_args.kwargs["delivery_status"] == "delivered"
    assert record.call_args.kwargs["payload"] == {
        "status": "delivered",
        "error_codes": [],
    }


def test_delivery_event_maps_read_status_without_regression():
    sb = MagicMock()
    rpc = MagicMock()
    rpc.execute.return_value = MagicMock(data=True)
    sb.rpc.return_value = rpc
    with patch("app.notifications.repository.get_supabase", return_value=sb):
        assert record_delivery_event(
            provider_event_id="wamid.1:read:1",
            provider_message_id="wamid.1",
            delivery_status="read",
            occurred_at="2026-07-21T10:00:00+00:00",
            payload={"status": "read"},
        )
    sb.rpc.assert_called_once_with(
        "record_notification_delivery_event",
        {
            "p_provider": "meta",
            "p_provider_event_id": "wamid.1:read:1",
            "p_provider_message_id": "wamid.1",
            "p_status": "read",
            "p_occurred_at": "2026-07-21T10:00:00+00:00",
            "p_payload": {"status": "read"},
        },
    )
