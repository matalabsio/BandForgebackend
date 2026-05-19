import logging
from urllib.parse import urlencode

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def _send_resend(*, to: str, subject: str, html: str) -> bool:
    settings = get_settings()
    if not settings.resend_api_key:
        logger.info("Resend not configured; skip email to %s — %s", to, subject)
        return settings.app_env != "production"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.email_from,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
            if resp.status_code >= 400:
                logger.error("Resend error %s: %s", resp.status_code, resp.text[:200])
                return False
            return True
    except httpx.HTTPError as exc:
        logger.exception("Resend request failed: %s", exc)
        return False


def _verify_link(token: str) -> str:
    base = get_settings().frontend_url.rstrip("/")
    return f"{base}/verify-email?{urlencode({'token': token})}"


def _reset_link(token: str) -> str:
    base = get_settings().frontend_url.rstrip("/")
    return f"{base}/reset-password?{urlencode({'token': token})}"


async def send_verification_email(*, to: str, token: str, name: str | None = None) -> bool:
    link = _verify_link(token)
    greeting = name or "there"
    html = f"""<div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;">
<h1 style="color:#0d1f3c;">Verify your BandForge email</h1>
<p>Hi {greeting},</p>
<p>Confirm your email to unlock your BandForge account.</p>
<p><a href="{link}" style="display:inline-block;background:#00bcd4;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">Verify email</a></p>
<p style="color:#666;font-size:14px;">Or paste this link: {link}</p>
<p style="color:#999;font-size:12px;">This link expires in 24 hours.</p>
</div>"""
    return await _send_resend(to=to, subject="Verify your BandForge email", html=html)


async def send_password_reset_email(*, to: str, token: str) -> bool:
    link = _reset_link(token)
    html = f"""<div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;">
<h1 style="color:#0d1f3c;">Reset your password</h1>
<p>We received a request to reset your BandForge password.</p>
<p><a href="{link}" style="display:inline-block;background:#0d1f3c;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">Reset password</a></p>
<p style="color:#666;font-size:14px;">Or paste this link: {link}</p>
<p style="color:#999;font-size:12px;">If you did not request this, ignore this email.</p>
</div>"""
    return await _send_resend(to=to, subject="Reset your BandForge password", html=html)
