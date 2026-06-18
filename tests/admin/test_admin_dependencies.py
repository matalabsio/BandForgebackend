"""Admin authorization dependency tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.admin.dependencies import (
    ADMIN_ACCESS_DENIED_DETAIL,
    ensure_admin_access,
    is_admin_email_allowed,
    require_admin,
    require_super_admin,
)
from app.auth.schemas import UserPublic
from app.config import reload_settings


def _user(
    *,
    role: str = "student",
    is_active: bool = True,
    email: str = "test@example.com",
) -> UserPublic:
    return UserPublic(
        id=uuid4(),
        email=email,
        role=role,
        is_active=is_active,
    )


@pytest.fixture(autouse=True)
def _clear_admin_email_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ADMIN_ALLOWED_EMAIL", raising=False)
    reload_settings()
    yield
    monkeypatch.delenv("ADMIN_ALLOWED_EMAIL", raising=False)
    reload_settings()


def test_is_admin_email_allowed_fail_closed_when_unset():
    assert is_admin_email_allowed("admin@test.com") is False


def test_is_admin_email_allowed_matches_configured_email(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_ALLOWED_EMAIL", "Allowed@Test.COM")
    reload_settings()
    assert is_admin_email_allowed("allowed@test.com") is True
    assert is_admin_email_allowed("other@test.com") is False


def test_require_admin_rejects_student():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(_user(role="student")))
    assert exc.value.status_code == 403


def test_require_admin_rejects_admin_when_env_unset():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(_user(role="admin", email="admin@test.com")))
    assert exc.value.status_code == 403
    assert exc.value.detail == ADMIN_ACCESS_DENIED_DETAIL


def test_require_admin_allows_matching_email(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_ALLOWED_EMAIL", "admin@test.com")
    reload_settings()
    user = asyncio.run(require_admin(_user(role="admin", email="admin@test.com")))
    assert user.role == "admin"


def test_require_admin_rejects_wrong_email_with_role(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_ALLOWED_EMAIL", "only@test.com")
    reload_settings()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(_user(role="super_admin", email="other@test.com")))
    assert exc.value.status_code == 403
    assert exc.value.detail == ADMIN_ACCESS_DENIED_DETAIL


def test_require_admin_rejects_inactive(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_ALLOWED_EMAIL", "admin@test.com")
    reload_settings()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            require_admin(_user(role="admin", email="admin@test.com", is_active=False))
        )
    assert exc.value.status_code == 403


def test_ensure_admin_access_same_as_require_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_ALLOWED_EMAIL", "admin@test.com")
    reload_settings()
    user = ensure_admin_access(_user(role="super_admin", email="admin@test.com"))
    assert user.role == "super_admin"


def test_require_super_admin_rejects_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_ALLOWED_EMAIL", "admin@test.com")
    reload_settings()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_super_admin(_user(role="admin", email="admin@test.com")))
    assert exc.value.status_code == 403


def test_require_super_admin_allows_super_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_ALLOWED_EMAIL", "admin@test.com")
    reload_settings()
    user = asyncio.run(
        require_super_admin(_user(role="super_admin", email="admin@test.com"))
    )
    assert user.role == "super_admin"
