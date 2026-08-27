"""Environment isolation guards — prevent staging from touching production.

Known production identifiers (non-secret):
- Supabase project ref ``nkwtxkhtsclyakympbno``
- Production Railway API host ``backend-production-a813.up.railway.app``
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.supabase_probe import project_ref_from_url

PRODUCTION_SUPABASE_PROJECT_REF = "nkwtxkhtsclyakympbno"
PRODUCTION_RAILWAY_API_HOST = "backend-production-a813.up.railway.app"
PRODUCTION_FRONTEND_HOSTS = frozenset(
    {
        "bandforgeuinew.vercel.app",
        "bandforge-web.vercel.app",
    }
)


def _host_from_url(url: str) -> str:
    try:
        return (urlparse(url.strip()).hostname or "").lower()
    except Exception:
        return ""


def assert_environment_safety(settings: Any) -> None:
    """Fail fast on unsafe staging configuration. No-op for non-staging."""
    env = str(getattr(settings, "app_env", "") or "").strip().lower()
    if env != "staging":
        return

    supabase_url = str(
        getattr(settings, "supabase_url_normalized", None)
        or getattr(settings, "supabase_url", "")
        or ""
    )
    ref = project_ref_from_url(supabase_url)
    if ref == PRODUCTION_SUPABASE_PROJECT_REF:
        raise RuntimeError(
            "APP_ENV=staging refuses production Supabase project "
            f"{PRODUCTION_SUPABASE_PROJECT_REF}. Set SUPABASE_URL to the staging project."
        )

    frontend = str(getattr(settings, "frontend_url", "") or "")
    frontend_host = _host_from_url(frontend)
    if frontend_host in PRODUCTION_FRONTEND_HOSTS:
        raise RuntimeError(
            "APP_ENV=staging refuses production FRONTEND_URL "
            f"({frontend_host}). Point FRONTEND_URL at the staging frontend."
        )

    redirect = str(getattr(settings, "google_redirect_uri", "") or "")
    redirect_host = _host_from_url(redirect)
    if redirect_host in PRODUCTION_FRONTEND_HOSTS:
        raise RuntimeError(
            "APP_ENV=staging refuses production GOOGLE_REDIRECT_URI. "
            "Use the staging frontend OAuth callback URL."
        )

    public_api = str(getattr(settings, "public_api_url", "") or "")
    public_host = _host_from_url(
        public_api if "://" in public_api else f"https://{public_api}"
    )
    if public_host == PRODUCTION_RAILWAY_API_HOST:
        raise RuntimeError(
            "APP_ENV=staging refuses PUBLIC_API_URL / RAILWAY_PUBLIC_DOMAIN "
            f"pointing at production host {PRODUCTION_RAILWAY_API_HOST}."
        )

    if bool(getattr(settings, "razorpay_enabled", False)):
        key_id = str(getattr(settings, "razorpay_key_id", "") or "").strip()
        if key_id.startswith("rzp_live_"):
            raise RuntimeError(
                "APP_ENV=staging refuses Razorpay LIVE keys (rzp_live_*). "
                "Use Razorpay TEST credentials (rzp_test_*)."
            )
        if key_id and not key_id.startswith("rzp_test_"):
            raise RuntimeError(
                "APP_ENV=staging requires Razorpay TEST key ids (rzp_test_*). "
                f"Got unrecognized RAZORPAY_KEY_ID prefix."
            )
        if not key_id or not str(
            getattr(settings, "razorpay_key_secret", "") or ""
        ).strip():
            raise RuntimeError(
                "APP_ENV=staging with RAZORPAY_ENABLED=true requires "
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET (test mode)."
            )
        if not str(getattr(settings, "razorpay_webhook_secret", "") or "").strip():
            raise RuntimeError(
                "APP_ENV=staging with RAZORPAY_ENABLED=true requires "
                "RAZORPAY_WEBHOOK_SECRET for the staging webhook endpoint."
            )
