"""Thin Razorpay wrapper.

Order creation goes through the official SDK; signature verification is done
locally with HMAC so it has no hard dependency on the SDK and is trivially
testable. Only ``RazorpayOrderPayload`` data is ever sent to Razorpay.
"""

from __future__ import annotations

import hashlib
import hmac
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.payments.exceptions import PaymentsDisabledError, RazorpayAuthError
from app.payments.schemas import RazorpayOrderPayload


def clear_client_cache() -> None:
    _client_for.cache_clear()


_credentials_probe_ok: bool | None = None
_env_mtime_at_probe: float | None = None


def set_credentials_probe_result(ok: bool) -> None:
    """Cache startup (or manual) Razorpay credential probe — avoids repeat API calls."""
    global _credentials_probe_ok
    _credentials_probe_ok = ok
    if not ok:
        clear_client_cache()


def clear_credentials_probe() -> None:
    global _credentials_probe_ok, _env_mtime_at_probe
    _credentials_probe_ok = None
    _env_mtime_at_probe = None


def credentials_ready() -> bool:
    """True when Razorpay is configured and the credential probe did not fail."""
    settings = get_settings()
    if not (
        settings.razorpay_enabled
        and settings.razorpay_key_id
        and settings.razorpay_key_secret
    ):
        return False
    if _credentials_probe_ok is False:
        from app.config import _ENV_FILE, reload_settings

        try:
            env_mtime = _ENV_FILE.stat().st_mtime
        except OSError:
            env_mtime = None
        if env_mtime is not None and env_mtime != _env_mtime_at_probe:
            reload_settings()
            ok, _ = probe_credentials()
            set_credentials_probe_result(ok)
            return ok
        return False
    return True


@lru_cache
def _client_for(key_id: str, key_secret: str) -> Any:
    import razorpay

    return razorpay.Client(auth=(key_id, key_secret))


def _client() -> Any:
    settings = get_settings()
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        raise PaymentsDisabledError()
    return _client_for(settings.razorpay_key_id, settings.razorpay_key_secret)


def _raise_on_auth_failure(exc: Exception) -> None:
    from razorpay.errors import BadRequestError

    if isinstance(exc, BadRequestError):
        msg = str(exc).lower()
        if "expired" in msg:
            raise RazorpayAuthError(
                detail=(
                    "Razorpay API key has expired. Generate new Test mode keys in "
                    "Razorpay Dashboard → Account & Settings → API Keys, update "
                    "backend/.env, then restart the backend."
                )
            ) from exc
        if "authentication failed" in msg:
            raise RazorpayAuthError() from exc


def probe_credentials() -> tuple[bool, str]:
    """Lightweight Razorpay auth check (lists one order)."""
    global _env_mtime_at_probe
    settings = get_settings()
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        return False, "RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET is unset"
    kid = settings.razorpay_key_id
    if kid.startswith("rrzp_"):
        return False, "RAZORPAY_KEY_ID typo — use rzp_test_ or rzp_live_, not rrzp_"
    clear_client_cache()
    try:
        _client().order.all({"count": 1})
        from app.config import _ENV_FILE

        try:
            _env_mtime_at_probe = _ENV_FILE.stat().st_mtime
        except OSError:
            _env_mtime_at_probe = None
        return True, "ok"
    except Exception as exc:
        from razorpay.errors import BadRequestError

        if isinstance(exc, BadRequestError):
            msg = str(exc).lower()
            if "expired" in msg:
                return (
                    False,
                    "API key expired — generate new Test mode keys in Razorpay Dashboard",
                )
            if "authentication failed" in msg:
                return False, "Authentication failed — key ID and secret do not match"
        return False, str(exc) or exc.__class__.__name__


def create_order(payload: RazorpayOrderPayload) -> dict[str, Any]:
    """Create a Razorpay order from a minimal payload.

    No ``notes`` are attached — user_id, plan_slug, and product metadata stay
    in Supabase. When ``RAZORPAY_CHECKOUT_CONFIG_ID`` is set, it is passed so
    Dashboard Payment Configuration controls checkout methods (UPI QR, Intent, etc.).
    """
    body: dict[str, Any] = {
        "amount": payload.amount,
        "currency": payload.currency,
        "receipt": payload.receipt,
        "payment_capture": 1,
    }
    config_id = (get_settings().razorpay_checkout_config_id or "").strip()
    if config_id:
        body["checkout_config_id"] = config_id
    try:
        client = _client()
        return client.order.create(body)
    except Exception as exc:
        _raise_on_auth_failure(exc)
        raise


def verify_payment_signature(
    *,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """Verify the checkout handler signature: HMAC_SHA256(order_id|payment_id)."""
    settings = get_settings()
    secret = settings.razorpay_key_secret
    if not secret:
        return False
    message = f"{razorpay_order_id}|{razorpay_payment_id}".encode()
    expected = hmac.new(
        secret.encode(), message, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, razorpay_signature)


def verify_webhook_signature(*, raw_body: bytes, signature: str) -> bool:
    """Verify a webhook using the raw request body and the webhook secret."""
    settings = get_settings()
    secret = settings.razorpay_webhook_secret
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
