import hashlib
import re
import secrets
from datetime import UTC, datetime

INDIA_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_india_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) >= 12 and digits.startswith("91"):
        return digits[-10:]
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def is_valid_india_phone(digits10: str) -> bool:
    return bool(INDIA_MOBILE_RE.match(digits10))


def phone_e164(digits10: str) -> str:
    return f"+91{digits10}"


def generate_otp_code(length: int | None = None) -> str:
    from app.auth.constants import OTP_LENGTH

    n = OTP_LENGTH if length is None else length
    return "".join(secrets.choice("0123456789") for _ in range(n))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_otp(code: str) -> str:
    return hash_token(code.strip())


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)
