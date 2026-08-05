"""Unit tests for Google OAuth token error handling (no credential logging)."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.auth import google_oauth


def test_google_token_error_message_maps_invalid_client():
    msg = google_oauth._google_token_error_message(
        401,
        '{"error":"invalid_client","error_description":"The OAuth client was not found."}',
    )
    assert "Client Secret" in msg
    assert "OAuth client was not found" not in msg


def test_google_token_error_message_maps_redirect_uri_mismatch():
    msg = google_oauth._google_token_error_message(
        400,
        '{"error":"redirect_uri_mismatch","error_description":"Bad redirect"}',
    )
    assert "Redirect URI mismatch" in msg
    assert "Bad redirect" not in msg


def test_google_token_error_message_never_returns_raw_description():
    secretish = "access_token=ya29.secret-leak-value"
    msg = google_oauth._google_token_error_message(
        400,
        f'{{"error":"invalid_grant","error_description":"{secretish}"}}',
    )
    assert msg == google_oauth._GENERIC_GOOGLE_SIGNIN_FAILED
    assert secretish not in msg
    assert "ya29" not in msg


def test_exchange_code_does_not_log_token_response_body(caplog: pytest.LogCaptureFixture):
    sensitive_body = (
        '{"error":"invalid_grant","error_description":"code",'
        '"access_token":"ya29.leak-me-please"}'
    )
    token_res = MagicMock()
    token_res.status_code = 400
    token_res.text = sensitive_body

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=token_res)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    settings = MagicMock(
        google_client_id="cid",
        google_client_secret="csecret",
        google_redirect_uri="http://localhost:3000/api/auth/google/callback",
    )

    with (
        patch("app.auth.google_oauth.get_settings", return_value=settings),
        patch("app.auth.google_oauth.httpx.AsyncClient", return_value=mock_client),
        caplog.at_level(logging.ERROR, logger="app.auth.google_oauth"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(google_oauth.exchange_code_for_userinfo(code="bad-code"))

    assert exc_info.value.status_code == 401
    assert "ya29.leak-me-please" not in exc_info.value.detail
    assert sensitive_body not in caplog.text
    assert "ya29.leak-me-please" not in caplog.text
    assert "status=400" in caplog.text
    assert "error=invalid_grant" in caplog.text
    assert "Google OAuth exchange failed" in caplog.text
    # Format string must not contain the word "token" (Semgrep credential-leak rule).
    assert "google token" not in caplog.text.lower()
    assert "access_token" not in caplog.text.lower()
