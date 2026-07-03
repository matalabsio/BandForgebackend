"""GET /auth/session — lightweight shell user resolution."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.constants import ACCESS_TOKEN_COOKIE
from app.auth.dependencies import get_current_session_user
from app.auth.jwt import create_access_token
from app.auth.schemas import SessionUser
from app.auth import service
from app.main import app

USER_ID = UUID("22222222-2222-4222-8222-222222222222")


def _session_user(**kwargs) -> SessionUser:
    defaults = {
        "id": USER_ID,
        "email": "student@test.com",
        "full_name": "Test Student",
        "role": "student",
        "avatar_display_url": None,
        "is_active": True,
    }
    defaults.update(kwargs)
    return SessionUser(**defaults)


def _user_row(**kwargs) -> dict:
    defaults = {
        "id": str(USER_ID),
        "full_name": "Test Student",
        "email": "student@test.com",
        "role": "student",
        "avatar_url": None,
        "is_active": True,
        "email_verified_at": "2026-01-01T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return defaults


def _mock_supabase_execute(data: list[dict] | None):
    mock_sb = MagicMock()
    mock_result = MagicMock()
    mock_result.data = data
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        mock_result
    )
    return mock_sb


def test_get_session_user_by_id_returns_session_user():
    mock_sb = _mock_supabase_execute([_user_row()])
    with patch("app.auth.service.get_supabase", return_value=mock_sb):
        user = asyncio.run(service.get_session_user_by_id(USER_ID))
    assert user.id == USER_ID
    assert user.full_name == "Test Student"
    assert user.role == "student"
    assert user.is_active is True


def test_get_session_user_by_id_not_found():
    mock_sb = _mock_supabase_execute([])
    with patch("app.auth.service.get_supabase", return_value=mock_sb):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(service.get_session_user_by_id(USER_ID))
    assert exc.value.status_code == 404


def test_get_session_user_by_id_inactive():
    mock_sb = _mock_supabase_execute([_user_row(is_active=False)])
    with patch("app.auth.service.get_supabase", return_value=mock_sb):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(service.get_session_user_by_id(USER_ID))
    assert exc.value.status_code == 403


def test_get_session_user_by_id_unverified_email_when_required(monkeypatch):
    monkeypatch.setattr(service, "_email_verification_required", lambda: True)
    mock_sb = _mock_supabase_execute(
        [_user_row(email_verified_at=None, email="student@test.com")]
    )
    with patch("app.auth.service.get_supabase", return_value=mock_sb):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(service.get_session_user_by_id(USER_ID))
    assert exc.value.status_code == 403


def test_session_route_returns_200():
    app.dependency_overrides[get_current_session_user] = lambda: _session_user()
    client = TestClient(app)
    try:
        token = create_access_token(user_id=USER_ID, email="student@test.com")
        res = client.get(
            "/auth/session",
            cookies={ACCESS_TOKEN_COOKIE: token},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == str(USER_ID)
        assert body["full_name"] == "Test Student"
        assert body["role"] == "student"
        assert "target_band" not in body
        assert "phone" not in body
    finally:
        app.dependency_overrides.clear()


def test_session_route_returns_401_without_token():
    client = TestClient(app)
    res = client.get("/auth/session")
    assert res.status_code == 401


def test_session_route_returns_401_with_invalid_token():
    client = TestClient(app)
    res = client.get(
        "/auth/session",
        cookies={ACCESS_TOKEN_COOKIE: "not-a-jwt"},
    )
    assert res.status_code == 401


def test_session_route_returns_403_inactive_user():
    async def _inactive():
        raise HTTPException(status_code=403, detail="Account is deactivated.")

    app.dependency_overrides[get_current_session_user] = _inactive
    client = TestClient(app)
    try:
        token = create_access_token(user_id=uuid4(), email="inactive@test.com")
        res = client.get(
            "/auth/session",
            cookies={ACCESS_TOKEN_COOKIE: token},
        )
        assert res.status_code == 403
    finally:
        app.dependency_overrides.clear()
