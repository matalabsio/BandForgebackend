import logging

import httpx

from app.auth.utils import phone_e164
from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_otp_sms(*, phone_e164: str, code: str) -> bool:
    """Send OTP via MSG91. Returns True if sent or skipped in demo; False on failure."""
    settings = get_settings()
    if not settings.msg91_auth_key or not settings.msg91_template_id:
        logger.info("MSG91 not configured; skipping SMS to %s", phone_e164[-4:])
        # Never silently skip real SMS in production.
        return settings.app_env != "production"

    digits = phone_e164.lstrip("+")
    if digits.startswith("91"):
        mobile = digits[2:]
    else:
        mobile = digits

    url = "https://control.msg91.com/api/v5/flow/"
    payload = {
        "template_id": settings.msg91_template_id,
        "short_url": "0",
        "recipients": [
            {
                "mobiles": f"91{mobile}",
                "otp": code,
            }
        ],
    }
    headers = {
        "authkey": settings.msg91_auth_key,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error("MSG91 error %s: %s", resp.status_code, resp.text[:200])
                return False
            return True
    except httpx.HTTPError as exc:
        logger.exception("MSG91 request failed: %s", exc)
        return False


async def send_otp_sms_digits(*, digits10: str, code: str) -> bool:
    return await send_otp_sms(phone_e164=phone_e164(digits10), code=code)
