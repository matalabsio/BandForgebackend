import logging
import hashlib
from html import escape
from urllib.parse import urlencode

from app.config import get_settings
from app.notifications.providers import ProviderError, ResendProvider

logger = logging.getLogger(__name__)


async def _send_resend(*, to: str, subject: str, html: str) -> bool:
    settings = get_settings()
    if not settings.resend_api_key:
        logger.info("Resend not configured; skip email to %s — %s", to, subject)
        return settings.app_env != "production"

    try:
        await ResendProvider(
            api_key=settings.resend_api_key, sender=settings.email_from
        ).send(
            to=to,
            subject=subject,
            html=html,
            idempotency_key=(
                "auth-"
                + hashlib.sha256(f"{to}\0{subject}\0{html}".encode()).hexdigest()
            ),
        )
        return True
    except ProviderError as exc:
        logger.warning("Resend request failed: %s", exc)
        return False


def _verify_link(token: str) -> str:
    base = get_settings().frontend_url.rstrip("/")
    return f"{base}/verify-email?{urlencode({'token': token})}"


def _reset_link(token: str) -> str:
    base = get_settings().frontend_url.rstrip("/")
    return f"{base}/reset-password?{urlencode({'token': token})}"


async def send_verification_email(*, to: str, token: str, name: str | None = None) -> bool:
    link = _verify_link(token)
    greeting = escape(name or "there")
    safe_link = escape(link, quote=True)
    html = f"""<div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;">
<h1 style="color:#0d1f3c;">Verify your BandForge email</h1>
<p>Hi {greeting},</p>
<p>Confirm your email to unlock your BandForge account.</p>
<p><a href="{safe_link}" style="display:inline-block;background:#00bcd4;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">Verify email</a></p>
<p style="color:#666;font-size:14px;">Or paste this link: {safe_link}</p>
<p style="color:#999;font-size:12px;">This link expires in 24 hours.</p>
</div>"""
    return await _send_resend(to=to, subject="Verify your BandForge email", html=html)


async def send_password_reset_email(*, to: str, token: str) -> bool:
    link = _reset_link(token)
    safe_link = escape(link, quote=True)
    html = f"""<div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;">
<h1 style="color:#0d1f3c;">Reset your password</h1>
<p>We received a request to reset your BandForge password.</p>
<p><a href="{safe_link}" style="display:inline-block;background:#0d1f3c;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">Reset password</a></p>
<p style="color:#666;font-size:14px;">Or paste this link: {safe_link}</p>
<p style="color:#999;font-size:12px;">If you did not request this, ignore this email.</p>
</div>"""
    return await _send_resend(to=to, subject="Reset your BandForge password", html=html)
