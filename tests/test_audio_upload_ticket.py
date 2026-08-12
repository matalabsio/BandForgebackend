"""HMAC tickets for browser → Railway listening audio PUTs."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.admin.audio_upload_ticket import (
    mint_audio_upload_ticket,
    parse_audio_upload_ticket,
    public_api_origin,
)


def _settings(**kwargs: object) -> MagicMock:
    settings = MagicMock()
    settings.jwt_secret = "test-jwt-secret"
    settings.public_api_url = ""
    for key, value in kwargs.items():
        setattr(settings, key, value)
    return settings


def test_ticket_roundtrip():
    with patch("app.admin.audio_upload_ticket.get_settings", return_value=_settings()):
        ticket = mint_audio_upload_ticket(
            key="bank/set/listening/part1/audio.mp3",
            admin_id="11111111-1111-1111-1111-111111111111",
            size_bytes=12_345,
        )
        payload = parse_audio_upload_ticket(ticket)
    assert payload["k"] == "bank/set/listening/part1/audio.mp3"
    assert payload["s"] == 12_345
    assert int(payload["exp"]) > 0


def test_ticket_rejects_tampering():
    with patch("app.admin.audio_upload_ticket.get_settings", return_value=_settings()):
        ticket = mint_audio_upload_ticket(
            key="bank/set/listening/part1/audio.mp3",
            admin_id="11111111-1111-1111-1111-111111111111",
            size_bytes=12_345,
        )
        with pytest.raises(HTTPException) as exc:
            parse_audio_upload_ticket(ticket[:-2] + "xx")
    assert exc.value.status_code == 403


def test_public_api_origin_prefers_settings():
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "POST",
            "path": "/admin/x",
            "headers": [(b"host", b"wrong.example")],
            "query_string": b"",
            "scheme": "https",
            "server": ("wrong.example", 443),
        }
    )
    with patch(
        "app.admin.audio_upload_ticket.get_settings",
        return_value=_settings(public_api_url="backend-production-a813.up.railway.app"),
    ):
        assert public_api_origin(request) == "https://backend-production-a813.up.railway.app"
