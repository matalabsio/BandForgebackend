import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

from app.auth.constants import (
    EMAIL_OTP_LENGTH,
    OTP_EXPIRE_MINUTES,
    OTP_MAX_ATTEMPTS,
    OTP_PURPOSE_LOGIN,
    OTP_RESEND_COOLDOWN_SECONDS,
)
from app.auth.demo_mode import otp_demo_mode
from app.auth.otp import OtpError
from app.auth.utils import hash_otp, normalize_email, utcnow
from app.config import get_settings
from app.db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def generate_email_otp_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(EMAIL_OTP_LENGTH))


def _require_normalized_email(email: str) -> str:
    normalized = normalize_email(email)
    if not normalized:
        raise OtpError("Email is required.", 400)
    return normalized


def _parse_ts(value: object, *, fallback_tz: object) -> datetime:
    if isinstance(value, datetime):
        exp = value
    elif isinstance(value, str) and value.endswith("Z"):
        exp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        exp = datetime.fromisoformat(str(value))
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=fallback_tz)  # type: ignore[arg-type]
    return exp


def _ensure_resend_ready_for_production() -> None:
    settings = get_settings()
    if settings.app_env != "production":
        return
    if settings.resend_api_key:
        return
    raise OtpError(
        "Email OTP is misconfigured. Resend credentials are required in production.",
        503,
    )


def _invalidate_email_otp(*, verification_id: str) -> None:
    sb = get_supabase()
    now = utcnow()
    sb.table("email_otp_verifications").update({"consumed_at": now.isoformat()}).eq(
        "id", verification_id
    ).is_("consumed_at", "null").execute()


def _rpc_payload(result: object) -> dict[str, Any]:
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def _create_email_otp_record(
    *,
    email: str,
    purpose: str,
    code_hash: str,
    expires_at: datetime,
) -> str:
    sb = get_supabase()
    try:
        created = _rpc_payload(
            sb.rpc(
                "create_email_otp_verification",
                {
                    "p_email": email,
                    "p_purpose": purpose,
                    "p_code_hash": code_hash,
                    "p_max_attempts": OTP_MAX_ATTEMPTS,
                    "p_expires_at": expires_at.isoformat(),
                    "p_cooldown_seconds": OTP_RESEND_COOLDOWN_SECONDS,
                },
            ).execute()
        )
    except Exception as exc:
        logger.exception("Failed to store email OTP: %s", exc)
        raise OtpError(
            "Email OTP storage is unavailable. Ensure auth migrations are applied.",
            503,
        ) from exc

    if created.get("cooldown"):
        wait = int(created.get("wait_seconds", OTP_RESEND_COOLDOWN_SECONDS))
        raise OtpError(
            f"Please wait {wait}s before requesting another OTP.",
            429,
        )

    if not created.get("created") or not created.get("verification_id"):
        raise OtpError(
            "Email OTP storage is unavailable. Ensure auth migrations are applied.",
            503,
        )

    return str(created["verification_id"])


def _consume_email_otp(*, verification_id: str, now: datetime) -> None:
    sb = get_supabase()
    consumed = (
        sb.table("email_otp_verifications")
        .update({"consumed_at": now.isoformat()})
        .eq("id", verification_id)
        .is_("consumed_at", "null")
        .gt("expires_at", now.isoformat())
        .execute()
    )
    if not consumed.data:
        raise OtpError("OTP expired or not found. Request a new code.", 401)


async def create_and_send_email_otp(
    *, email: str, purpose: str = OTP_PURPOSE_LOGIN
) -> str | None:
    """Create email OTP record; send via Resend when configured. Returns demo hint if applicable."""
    settings = get_settings()
    now = utcnow()
    expires = now + timedelta(minutes=OTP_EXPIRE_MINUTES)
    normalized = _require_normalized_email(email)

    _ensure_resend_ready_for_production()

    code = generate_email_otp_code()
    if otp_demo_mode(settings) and settings.auth_demo_otp:
        code = settings.auth_demo_otp

    verification_id = _create_email_otp_record(
        email=normalized,
        purpose=purpose,
        code_hash=hash_otp(code),
        expires_at=expires,
    )

    from app.auth.email import send_login_otp_email

    sent = False
    try:
        sent = await send_login_otp_email(
            to=normalized, code=code, expires_minutes=OTP_EXPIRE_MINUTES
        )
    except Exception as exc:
        logger.exception("Failed to send email OTP via Resend: %s", exc)
        if not otp_demo_mode(settings):
            _invalidate_email_otp(verification_id=verification_id)
            raise OtpError("Could not send OTP. Try again later.", 503) from exc
    else:
        if not sent and not otp_demo_mode(settings):
            _invalidate_email_otp(verification_id=verification_id)
            raise OtpError("Could not send OTP. Try again later.", 503)

    if otp_demo_mode(settings):
        return (
            "Demo mode: use the configured demo OTP or any 6-digit code if open OTP is enabled."
        )
    return None


async def verify_email_otp_code(
    *, email: str, code: str, purpose: str = OTP_PURPOSE_LOGIN
) -> None:
    settings = get_settings()
    sb = get_supabase()
    now = utcnow()
    normalized = _require_normalized_email(email)

    if settings.auth_open_otp and otp_demo_mode(settings):
        return

    if otp_demo_mode(settings) and settings.auth_demo_otp and code == settings.auth_demo_otp:
        row = (
            sb.table("email_otp_verifications")
            .select("id")
            .eq("email", normalized)
            .eq("purpose", purpose)
            .is_("consumed_at", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if row.data:
            _consume_email_otp(verification_id=str(row.data[0]["id"]), now=now)
        return

    result = (
        sb.table("email_otp_verifications")
        .select("*")
        .eq("email", normalized)
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

    exp = _parse_ts(record["expires_at"], fallback_tz=now.tzinfo)

    if now > exp:
        raise OtpError("OTP expired. Request a new code.", 401)

    if hash_otp(code) != record["code_hash"]:
        increment = _rpc_payload(
            sb.rpc(
                "increment_email_otp_attempt",
                {"p_verification_id": str(record["id"])},
            ).execute()
        )
        attempts = int(increment.get("attempts", record["attempts"]))
        max_attempts = int(increment.get("max_attempts", record["max_attempts"]))
        if attempts >= max_attempts:
            raise OtpError("Too many attempts. Request a new OTP.", 429)
        raise OtpError("Invalid OTP.", 401)

    _consume_email_otp(verification_id=str(record["id"]), now=now)
