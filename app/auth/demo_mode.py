"""Shared OTP demo-mode detection (email + phone)."""

from typing import Any

from app.config import get_settings


def otp_demo_mode(settings: Any | None = None) -> bool:
    """True when explicit demo flags are on — not merely because APP_ENV is development."""
    s = settings or get_settings()
    if s.app_env.strip().lower() == "production":
        return False
    return bool(
        s.auth_demo_otp_enabled
        or s.auth_open_otp
        or (s.auth_demo_otp or "").strip()
    )
