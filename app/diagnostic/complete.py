"""Persist diagnostic completion for logged-in users."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.db.supabase_client import get_supabase
from app.diagnostic.schemas import DiagnosticCompleteRequest, DiagnosticCompleteResponse


def _now() -> datetime:
    return datetime.now(UTC)


def complete_diagnostic(
    *,
    user_id: UUID,
    body: DiagnosticCompleteRequest,
) -> DiagnosticCompleteResponse:
    sb = get_supabase()
    completed_at = body.completed_at or _now()
    payload: dict[str, Any] = {
        "user_id": str(user_id),
        "client_attempt_id": body.client_attempt_id.strip(),
        "status": "completed",
        "listening_band": body.listening_band,
        "reading_band": body.reading_band,
        "writing_band": body.writing_band,
        "speaking_band": body.speaking_band,
        "aggregate_band": body.aggregate_band,
        "review": body.review,
        "pack_version": body.pack_version,
        "started_at": body.started_at.isoformat() if body.started_at else None,
        "completed_at": completed_at.isoformat()
        if isinstance(completed_at, datetime)
        else completed_at,
    }

    existing = (
        sb.table("diagnostic_attempts")
        .select("id")
        .eq("user_id", str(user_id))
        .eq("client_attempt_id", payload["client_attempt_id"])
        .limit(1)
        .execute()
    ).data

    if existing:
        row_id = str(existing[0]["id"])
        sb.table("diagnostic_attempts").update(payload).eq("id", row_id).execute()
    else:
        inserted = sb.table("diagnostic_attempts").insert(payload).execute()
        if not inserted.data:
            raise RuntimeError("Could not save diagnostic attempt.")
        row_id = str(inserted.data[0]["id"])

    return DiagnosticCompleteResponse(
        id=row_id,
        client_attempt_id=payload["client_attempt_id"],
    )
