"""Tests for GET /api/payments/ops-status (admin readiness)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.config import reload_settings
from app.main import app

ADMIN_ID = UUID("00000000-0000-4000-8000-0000000000a9")
STUDENT_ID = UUID("00000000-0000-4000-8000-0000000000a1")


def _admin() -> UserPublic:
    return UserPublic(
        id=ADMIN_ID,
        email="admin@test.com",
        full_name="Admin",
        role="admin",
        is_active=True,
    )


def _student() -> UserPublic:
    return UserPublic(
        id=STUDENT_ID,
        email="student@example.com",
        full_name="Student",
        role="student",
        is_active=True,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _admin_email(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_ALLOWED_EMAIL", "admin@test.com")
    reload_settings()
    yield
    monkeypatch.delenv("ADMIN_ALLOWED_EMAIL", raising=False)
    reload_settings()
    app.dependency_overrides.clear()


def test_ops_status_requires_auth(client: TestClient):
    res = client.get("/api/payments/ops-status")
    assert res.status_code in (401, 403)


def test_ops_status_rejects_student(client: TestClient):
    app.dependency_overrides[get_current_user] = _student
    res = client.get("/api/payments/ops-status")
    assert res.status_code == 403


def test_ops_status_shape_for_admin(client: TestClient):
    app.dependency_overrides[get_current_user] = _admin
    settings = SimpleNamespace(
        razorpay_enabled=True,
        razorpay_key_id="rzp_test_ABCDEFGH",
        razorpay_key_secret="secret",
        razorpay_webhook_secret="whsec",
        app_env="development",
    )
    with (
        patch("app.payments.service.get_settings", return_value=settings),
        patch("app.payments.razorpay_client.get_cached_credentials_probe", return_value=True),
    ):
        res = client.get("/api/payments/ops-status")
    assert res.status_code == 200
    body = res.json()
    assert body["razorpay_enabled"] is True
    assert body["mode"] == "TEST"
    assert body["key_id_prefix"] == "rzp_test_ABC"
    assert body["webhook_secret_configured"] is True
    assert body["credentials_probe_ok"] is True
    assert body["app_env"] == "development"
    assert "secret" not in body
    assert "razorpay_key_secret" not in body
