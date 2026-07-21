"""Current-user notification preference operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.db.supabase_client import get_supabase
from app.notifications import WHATSAPP_CONSENT_VERSION
from app.speaking.schemas import (
    NotificationPreferencesResponse,
    PatchNotificationPreferencesRequest,
)

PREFERENCE_COLUMNS = (
    "id, phone, phone_verified_at, is_active, speaking_release_email_enabled, "
    "speaking_release_whatsapp_enabled, speaking_release_whatsapp_consented_at, "
    "speaking_release_whatsapp_consent_version"
)


def _load(user_id: UUID) -> dict[str, Any]:
    result = (
        get_supabase()
        .table("users")
        .select(PREFERENCE_COLUMNS)
        .eq("id", str(user_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return result.data[0]


def _mask_phone(phone: Any) -> str | None:
    value = str(phone or "").strip()
    if not value:
        return None
    return f"{value[:3]}•••••{value[-2:]}" if len(value) > 5 else "••••"


def _response(row: dict[str, Any]) -> NotificationPreferencesResponse:
    eligible = bool(
        row.get("is_active", True)
        and row.get("phone")
        and row.get("phone_verified_at")
    )
    enabled = bool(row.get("speaking_release_whatsapp_enabled")) and eligible
    return NotificationPreferencesResponse(
        email_enabled=bool(row.get("speaking_release_email_enabled", True)),
        whatsapp_enabled=enabled,
        whatsapp_eligible=eligible,
        masked_phone=_mask_phone(row.get("phone")),
        consent_version=(
            str(row["speaking_release_whatsapp_consent_version"])
            if row.get("speaking_release_whatsapp_consent_version")
            else None
        ),
    )


def get_preferences(user_id: UUID) -> NotificationPreferencesResponse:
    return _response(_load(user_id))


def patch_preferences(
    user_id: UUID, body: PatchNotificationPreferencesRequest
) -> NotificationPreferencesResponse:
    row = _load(user_id)
    changes: dict[str, Any] = {}
    if body.email_enabled is not None:
        changes["speaking_release_email_enabled"] = body.email_enabled
    if body.whatsapp_enabled is True:
        if body.consent_confirmation != WHATSAPP_CONSENT_VERSION:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Explicit WhatsApp consent confirmation is required.",
            )
        if not row.get("is_active", True):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is inactive.")
        if not row.get("phone") or not row.get("phone_verified_at"):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A current verified phone number is required.",
            )
        changes.update(
            {
                "speaking_release_whatsapp_enabled": True,
                "speaking_release_whatsapp_consented_at": datetime.now(UTC).isoformat(),
                "speaking_release_whatsapp_consent_version": WHATSAPP_CONSENT_VERSION,
            }
        )
    elif body.whatsapp_enabled is False:
        # Preserve timestamp/version for audit; enablement controls future delivery.
        changes["speaking_release_whatsapp_enabled"] = False

    if changes:
        changes["updated_at"] = datetime.now(UTC).isoformat()
        result = (
            get_supabase()
            .table("users")
            .update(changes)
            .eq("id", str(user_id))
            .select(PREFERENCE_COLUMNS)
            .execute()
        )
        row = result.data[0] if result.data else {**row, **changes}
    return _response(row)
