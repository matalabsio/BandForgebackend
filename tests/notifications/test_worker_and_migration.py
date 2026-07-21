import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.notifications.providers import DeliveryResult, ProviderError
from app.notifications.worker import deliver, run_batch

MIGRATION = (
    Path(__file__).parents[2]
    / "supabase/migrations/20260721127000_speaking_release_notifications.sql"
)
INDEX_MIGRATION = (
    Path(__file__).parents[2]
    / "supabase/migrations/20260721128000_speaking_phase13_indexes.sql"
)


def _row(**overrides):
    row = {
        "id": str(uuid4()),
        "review_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "approval_version": 2,
        "channel": "email",
        "recipient_snapshot": "student@example.com",
        "payload": {"student_name": "Student"},
        "attempts": 1,
        "max_attempts": 3,
        "lease_token": str(uuid4()),
    }
    return {**row, **overrides}


def _settings():
    return SimpleNamespace(
        frontend_url="https://app.example.com",
        resend_api_key="resend-key",
        email_from="BandForge <reports@example.com>",
        meta_whatsapp_enabled=True,
        meta_whatsapp_graph_version="v23.0",
        meta_whatsapp_phone_number_id="phone-id",
        meta_whatsapp_access_token="token",
        meta_whatsapp_template_name="speaking_ready",
        meta_whatsapp_template_language="en",
        notification_worker_batch_size=20,
        notification_worker_lease_seconds=120,
        notification_worker_concurrency=2,
    )


def test_worker_preflight_cancels_stale_release_without_provider_call():
    row = _row()
    with (
        patch("app.notifications.worker.repository.preflight", return_value=False),
        patch("app.notifications.worker.repository.mark_cancelled") as cancel,
        patch("app.notifications.worker.ResendProvider.send", new=AsyncMock()) as send,
    ):
        asyncio.run(deliver(row))
    cancel.assert_called_once_with(row)
    send.assert_not_awaited()


def test_worker_send_retry_and_dead_letter_paths():
    row = _row()
    with (
        patch("app.notifications.worker.get_settings", return_value=_settings()),
        patch("app.notifications.worker.repository.preflight", return_value=True),
        patch(
            "app.notifications.worker.ResendProvider.send",
            new=AsyncMock(return_value=DeliveryResult("email-1")),
        ),
        patch("app.notifications.worker.repository.mark_sent") as sent,
    ):
        asyncio.run(deliver(row))
    sent.assert_called_once_with(row, "email-1")

    with (
        patch("app.notifications.worker.get_settings", return_value=_settings()),
        patch("app.notifications.worker.repository.preflight", return_value=True),
        patch(
            "app.notifications.worker.ResendProvider.send",
            new=AsyncMock(side_effect=ProviderError("temporary", retryable=True)),
        ),
        patch("app.notifications.worker.repository.mark_failure") as failed,
    ):
        asyncio.run(deliver(row))
    assert failed.call_args.kwargs["retryable"] is True
    assert failed.call_args.kwargs["next_attempt_at"] is not None

    dead = _row(attempts=3, max_attempts=3)
    with (
        patch("app.notifications.worker.get_settings", return_value=_settings()),
        patch("app.notifications.worker.repository.preflight", return_value=True),
        patch(
            "app.notifications.worker.ResendProvider.send",
            new=AsyncMock(side_effect=ProviderError("still down", retryable=True)),
        ),
        patch("app.notifications.worker.repository.mark_failure") as failed,
    ):
        asyncio.run(deliver(dead))
    assert failed.call_args.kwargs["next_attempt_at"] is None


def test_worker_claims_with_configured_lease_and_batch():
    settings = _settings()
    with (
        patch("app.notifications.worker.get_settings", return_value=settings),
        patch("app.notifications.worker.repository.claim", return_value=[]) as claim,
    ):
        assert asyncio.run(run_batch()) == 0
    claim.assert_called_once_with(batch_size=20, lease_seconds=120)


def test_migration_has_atomic_claim_enqueue_idempotency_and_reopen_cancellation():
    sql = MIGRATION.read_text()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "lease_expires_at < now()" in sql
    assert "UNIQUE(event_type, review_id, approval_version, channel)" in sql
    assert "speaking_release_whatsapp_consent_version = 'speaking_release_whatsapp_v1'" in sql
    assert "INSERT INTO notification_outbox" in sql
    assert "status IN ('queued','retry','processing')" in sql
    assert "users_invalidate_whatsapp_consent_on_phone_change" in sql
    assert "record_notification_delivery_event(" in sql
    assert "ON CONFLICT(provider, provider_event_id) DO NOTHING" in sql
    assert "SELECT u.* INTO v_owner" in sql
    assert "REVOKE ALL ON TABLE notification_outbox" in sql


def test_phase13_foreign_keys_have_covering_indexes():
    sql = INDEX_MIGRATION.read_text()
    for index_name in (
        "idx_speaking_responses_question",
        "idx_speaking_reviews_reviewer",
        "idx_speaking_reviews_reopened_by",
        "idx_notification_outbox_review_version",
        "idx_notification_outbox_attempt",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {index_name}" in sql
