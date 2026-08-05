from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.notifications.preferences import get_preferences, patch_preferences
from app.speaking.schemas import PatchNotificationPreferencesRequest


def _user(**overrides):
    row = {
        "id": str(uuid4()),
        "phone": "+919876543210",
        "phone_verified_at": "2026-07-21T10:00:00Z",
        "is_active": True,
        "speaking_release_email_enabled": True,
        "plan_reminders_email": True,
        "speaking_release_whatsapp_enabled": False,
        "speaking_release_whatsapp_consented_at": None,
        "speaking_release_whatsapp_consent_version": None,
    }
    return {**row, **overrides}


def test_preferences_mask_phone_and_compute_eligibility():
    with patch("app.notifications.preferences._load", return_value=_user()):
        result = get_preferences(uuid4())
    assert result.whatsapp_eligible is True
    assert result.plan_reminders_email is True
    assert result.masked_phone.endswith("10")
    assert "+919876543210" not in result.masked_phone


def test_patch_plan_reminders_email():
    chain = MagicMock()
    chain.update.return_value = chain
    chain.eq.return_value = chain
    chain.select.return_value = chain
    result = MagicMock()
    result.data = []
    chain.execute.return_value = result
    sb = MagicMock()
    sb.table.return_value = chain

    with (
        patch("app.notifications.preferences._load", return_value=_user()),
        patch("app.notifications.preferences.get_supabase", return_value=sb),
    ):
        updated = patch_preferences(
            uuid4(), PatchNotificationPreferencesRequest(plan_reminders_email=False)
        )
    update = chain.update.call_args.args[0]
    assert update["plan_reminders_email"] is False
    assert updated.plan_reminders_email is False


def test_enable_whatsapp_requires_exact_consent_and_verified_phone():
    with patch("app.notifications.preferences._load", return_value=_user()):
        with pytest.raises(HTTPException) as exc:
            patch_preferences(
                uuid4(),
                PatchNotificationPreferencesRequest(
                    whatsapp_enabled=True, consent_confirmation="yes"
                ),
            )
    assert exc.value.status_code == 422

    with patch(
        "app.notifications.preferences._load",
        return_value=_user(phone_verified_at=None),
    ):
        with pytest.raises(HTTPException) as exc:
            patch_preferences(
                uuid4(),
                PatchNotificationPreferencesRequest(
                    whatsapp_enabled=True,
                    consent_confirmation="speaking_release_whatsapp_v1",
                ),
            )
    assert exc.value.status_code == 409


def test_enable_and_disable_whatsapp_preserves_audit_consent():
    chain = MagicMock()
    chain.update.return_value = chain
    chain.eq.return_value = chain
    chain.select.return_value = chain
    result = MagicMock()
    result.data = []
    chain.execute.return_value = result
    sb = MagicMock()
    sb.table.return_value = chain

    with (
        patch("app.notifications.preferences._load", return_value=_user()),
        patch("app.notifications.preferences.get_supabase", return_value=sb),
    ):
        enabled = patch_preferences(
            uuid4(),
            PatchNotificationPreferencesRequest(
                email_enabled=False,
                whatsapp_enabled=True,
                consent_confirmation="speaking_release_whatsapp_v1",
            ),
        )
    update = chain.update.call_args.args[0]
    assert update["speaking_release_whatsapp_enabled"] is True
    assert update["speaking_release_whatsapp_consented_at"]
    assert enabled.email_enabled is False

    chain.update.reset_mock()
    with (
        patch(
            "app.notifications.preferences._load",
            return_value=_user(
                speaking_release_whatsapp_enabled=True,
                speaking_release_whatsapp_consented_at="2026-07-21T10:00:00Z",
                speaking_release_whatsapp_consent_version="speaking_release_whatsapp_v1",
            ),
        ),
        patch("app.notifications.preferences.get_supabase", return_value=sb),
    ):
        patch_preferences(
            uuid4(), PatchNotificationPreferencesRequest(whatsapp_enabled=False)
        )
    update = chain.update.call_args.args[0]
    assert update["speaking_release_whatsapp_enabled"] is False
    assert "speaking_release_whatsapp_consented_at" not in update
