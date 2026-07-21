"""Leased notification outbox worker.

Run once: python -m app.notifications.worker --once
Run continuously: python -m app.notifications.worker
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import get_settings
from app.notifications import repository
from app.notifications.providers import (
    MetaWhatsAppProvider,
    ProviderError,
    ResendProvider,
)
from app.notifications.templates import (
    speaking_release_email_html,
    speaking_release_whatsapp_components,
    speaking_report_url,
)

logger = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    text = re.sub(r"https?://\S+", "[url]", str(exc))
    text = re.sub(r"\+?\d[\d\s-]{7,}\d", "[recipient]", text)
    return " ".join(text.split())[:500] or exc.__class__.__name__


def _next_attempt(attempt: int) -> str:
    base = min(3600, 15 * (2 ** max(0, attempt - 1)))
    delay = base + random.uniform(0, base * 0.25)
    return (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()


async def deliver(row: dict[str, Any]) -> None:
    if not repository.preflight(row):
        repository.mark_cancelled(row)
        logger.info(
            "notification_cancelled job_id=%s channel=%s reason=stale_release",
            row.get("id"),
            row.get("channel"),
        )
        return
    settings = get_settings()
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    raw_test_number = payload.get("test_number")
    try:
        test_number = int(raw_test_number) if raw_test_number is not None else None
    except (TypeError, ValueError):
        test_number = None
    report_url = speaking_report_url(
        settings.frontend_url, str(row["attempt_id"]), test_number
    )
    try:
        if row["channel"] == "email":
            result = await ResendProvider(
                api_key=settings.resend_api_key,
                sender=settings.email_from,
            ).send(
                to=str(row["recipient_snapshot"]),
                subject="Your BandForge Speaking report is ready",
                html=speaking_release_email_html(
                    student_name=payload.get("student_name"),
                    examiner_name=payload.get("examiner_name"),
                    report_url=report_url,
                ),
                idempotency_key=f"notification-{row['id']}",
            )
        elif row["channel"] == "whatsapp":
            if not settings.meta_whatsapp_enabled:
                raise ProviderError("WhatsApp delivery is disabled", retryable=False)
            result = await MetaWhatsAppProvider(
                graph_version=settings.meta_whatsapp_graph_version,
                phone_number_id=settings.meta_whatsapp_phone_number_id,
                access_token=settings.meta_whatsapp_access_token,
                template_name=settings.meta_whatsapp_template_name,
                template_language=settings.meta_whatsapp_template_language,
            ).send(
                to=str(row["recipient_snapshot"]),
                components=speaking_release_whatsapp_components(
                    student_name=payload.get("student_name"), report_url=report_url
                ),
            )
        else:
            raise ProviderError("unsupported notification channel", retryable=False)
        if repository.mark_sent(row, result.provider_message_id):
            logger.info(
                "notification_sent job_id=%s channel=%s",
                row.get("id"),
                row.get("channel"),
            )
        else:
            logger.warning(
                "notification_sent_without_state_update job_id=%s channel=%s",
                row.get("id"),
                row.get("channel"),
            )
    except Exception as exc:
        retryable = exc.retryable if isinstance(exc, ProviderError) else True
        error = _safe_error(exc)
        repository.mark_failure(
            row,
            error=error,
            retryable=retryable,
            next_attempt_at=(
                _next_attempt(int(row["attempts"]))
                if retryable and int(row["attempts"]) < int(row["max_attempts"])
                else None
            ),
        )
        logger.warning(
            "notification_failed job_id=%s channel=%s retryable=%s error=%s",
            row.get("id"),
            row.get("channel"),
            retryable,
            error,
        )


async def run_batch() -> int:
    settings = get_settings()
    rows = repository.claim(
        batch_size=settings.notification_worker_batch_size,
        lease_seconds=settings.notification_worker_lease_seconds,
    )
    semaphore = asyncio.Semaphore(max(1, settings.notification_worker_concurrency))

    async def bounded(row: dict[str, Any]) -> None:
        async with semaphore:
            await deliver(row)

    await asyncio.gather(*(bounded(row) for row in rows))
    if rows:
        logger.info("notification_batch_complete count=%d", len(rows))
    return len(rows)


async def run(*, once: bool = False) -> None:
    while True:
        count = await run_batch()
        if once:
            return
        if count == 0:
            await asyncio.sleep(max(0.25, get_settings().notification_worker_poll_seconds))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(once=args.once))


if __name__ == "__main__":
    main()
