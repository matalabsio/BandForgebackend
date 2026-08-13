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
        "ielts_purpose": None,
        "ielts_goal": None,
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
    assert user.ielts_purpose is None
    assert user.ielts_goal is None


def test_get_session_user_by_id_includes_ielts_purpose_and_goal():
    mock_sb = _mock_supabase_execute(
        [_user_row(ielts_purpose="immigration", ielts_goal="australian_pr")]
    )
    with patch("app.auth.service.get_supabase", return_value=mock_sb):
        user = asyncio.run(service.get_session_user_by_id(USER_ID))
    assert user.ielts_purpose == "immigration"
    assert user.ielts_goal == "australian_pr"


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
        assert body["ielts_purpose"] is None
        assert body["ielts_goal"] is None
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


def test_refresh_session_rejects_inactive_user():
    from datetime import datetime, timedelta, timezone

    from app.auth.jwt import create_refresh_token
    from app.auth.utils import hash_token

    session_id = uuid4()
    refresh = create_refresh_token(user_id=USER_ID, session_id=session_id)
    now = datetime.now(timezone.utc)
    session_row = {
        "id": str(session_id),
        "user_id": str(USER_ID),
        "token_hash": hash_token(refresh),
        "revoked_at": None,
        "expires_at": (now + timedelta(days=30)).isoformat(),
    }

    mock_sb = MagicMock()
    session_result = MagicMock()
    session_result.data = [session_row]
    user_result = MagicMock()
    user_result.data = [_user_row(is_active=False)]

    table = mock_sb.table.return_value
    # refresh_sessions select chain
    select_chain = table.select.return_value
    select_chain.eq.return_value.eq.return_value.is_.return_value.limit.return_value.execute.return_value = (
        session_result
    )
    # users select chain (second table("users") call)
    def _table(name: str):
        t = MagicMock()
        if name == "refresh_sessions":
            t.select.return_value.eq.return_value.eq.return_value.is_.return_value.limit.return_value.execute.return_value = (
                session_result
            )
        else:
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
                user_result
            )
        return t

    mock_sb.table.side_effect = _table

    with patch("app.auth.service.get_supabase", return_value=mock_sb):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(service.refresh_session(refresh_token=refresh))
    assert exc.value.status_code == 403
    assert "deactivated" in str(exc.value.detail).lower()