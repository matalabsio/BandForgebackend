import logging
from datetime import timedelta

from app.auth.constants import (
    OTP_EXPIRE_MINUTES,
    OTP_MAX_ATTEMPTS,
    OTP_PURPOSE_LOGIN,
)
from app.auth.utils import generate_otp_code, hash_otp, utcnow
from app.config import get_settings
from app.db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


class OtpError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _demo_mode() -> bool:
    return get_settings().app_env != "production" or get_settings().auth_demo_otp_enabled


async def create_and_send_otp(*, phone: str, purpose: str = OTP_PURPOSE_LOGIN) -> str | None:
    """Create OTP record; send via MSG91 when configured. Returns demo hint if applicable."""
    settings = get_settings()
    sb = get_supabase()
    now = utcnow()
    expires = now + timedelta(minutes=OTP_EXPIRE_MINUTES)

    code = generate_otp_code()
    if settings.auth_demo_otp:
        code = settings.auth_demo_otp

    try:
        sb.table("otp_verifications").insert(
            {
                "phone": phone,
                "code_hash": hash_otp(code),
                "purpose": purpose,
                "attempts": 0,
                "max_attempts": OTP_MAX_ATTEMPTS,
                "expires_at": expires.isoformat(),
            }
        ).execute()
    except Exception as exc:
        logger.exception("Failed to store OTP: %s", exc)
        raise OtpError(
            "Phone OTP storage is unavailable. Ensure auth migrations are applied.",
            503,
        ) from exc

    from app.auth.sms import send_otp_sms_digits

    sent = await send_otp_sms_digits(digits10=phone, code=code)
    if not sent and not _demo_mode():
        raise OtpError("Could not send OTP. Try again later.", 503)

    if _demo_mode():
        return (
            "Demo mode: use the configured demo OTP or any 6-digit code if open OTP is enabled."
        )
    return None


def phone_e164_from_digits(digits10: str) -> str:
    return f"+91{digits10}"


async def verify_otp_code(*, phone: str, code: str, purpose: str = OTP_PURPOSE_LOGIN) -> None:
    settings = get_settings()
    sb = get_supabase()
    now = utcnow()

    if settings.auth_open_otp and _demo_mode():
        return

    if settings.auth_demo_otp and code == settings.auth_demo_otp:
        row = (
            sb.table("otp_verifications")
            .select("id")
            .eq("phone", phone)
            .eq("purpose", purpose)
            .is_("consumed_at", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if row.data:
            sb.table("otp_verifications").update({"consumed_at": now.isoformat()}).eq(
                "id", row.data[0]["id"]
            ).execute()
        return

    result = (
        sb.table("otp_verifications")
        .select("*")
        .eq("phone", phone)
        .eq("purpose", purpose)
        .is_("consumed_at", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise OtpError("OTP expired or not found. Request a new code.", 401)

    record = result.data[0]
    if record["attempts"] >= record["max_attempts"]:
        raise OtpError("Too many attempts. Request a new OTP.", 429)

    expires_at = record["expires_at"]
    if isinstance(expires_at, str) and expires_at.endswith("Z"):
        from datetime import datetime

        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    else:
        from datetime import datetime

        exp = datetime.fromisoformat(str(expires_at))

    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=now.tzinfo)

    if now > exp:
        raise OtpError("OTP expired. Request a new code.", 401)

    if hash_otp(code) != record["code_hash"]:
        sb.table("otp_verifications").update(
            {"attempts": record["attempts"] + 1}
        ).eq("id", record["id"]).execute()
        raise OtpError("Invalid OTP.", 401)

    sb.table("otp_verifications").update({"consumed_at": now.isoformat()}).eq(
        "id", record["id"]
    ).execute()
