"""Public ops routes — smoke-test the API without auth or the frontend."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from app.cache.hybrid_cache import redis_status
from app.config import get_settings, settings_diagnostics
from app.supabase_probe import probe_supabase, project_ref_from_url

router = APIRouter(prefix="/api/status", tags=["status"])

SERVICE = "bandforge-api"
VERSION = "0.1.0"


def _google_oauth_state() -> str:
    s = get_settings()
    if not (s.google_client_id and s.google_client_secret and s.google_redirect_uri):
        return "off"
    if "localhost" in s.google_redirect_uri or "127.0.0.1" in s.google_redirect_uri:
        return "configured_localhost_redirect"
    return "configured"


def _r2_state() -> str:
    s = get_settings()
    if s.r2_access_key_id and s.r2_secret_access_key and s.r2_bucket_name:
        return "configured"
    return "off"


def _stream_state() -> str:
    s = get_settings()
    account = (s.cloudflare_account_id or "").strip()
    token = (s.cloudflare_api_token or "").strip()
    customer = (s.stream_customer_code or "").strip()
    if account and token and customer:
        return "configured"
    if account and token:
        return "missing_customer_code"
    return "missing_token" if account else "off"


@router.get("/ping")
def ping() -> dict[str, str]:
    """Minimal liveness — use for Railway/Vercel uptime checks."""
    return {"status": "ok", "service": SERVICE}


@router.get("")
def status_summary(
    probe: bool = Query(
        False,
        description="When true, ping Supabase (adds ~1s; does not scan all tables).",
    ),
) -> dict[str, object]:
    """
    API is up + which integrations are configured.

    Deeper checks (no auth):
    - GET /api/status/ready — Supabase reachable
    - GET /api/tests/db-check — all Phase 2 tables
    - GET /api/tests/r2-check — Cloudflare R2 upload + signed URL
    """
    settings = get_settings()
    diag = settings_diagnostics()
    checks: dict[str, object] = {
        "supabase_configured": bool(
            settings.supabase_url.strip() and settings.supabase_secret_key.strip()
        ),
        "redis": redis_status(),
        "google_oauth": _google_oauth_state(),
        "r2": _r2_state(),
        "stream": _stream_state(),
    }
    if probe:
        host_status, hint = probe_supabase(
            settings.supabase_url_normalized,
            settings.supabase_secret_key,
        )
        checks["supabase"] = host_status
        if hint:
            checks["supabase_hint"] = hint

    return {
        "status": "ok",
        "service": SERVICE,
        "version": VERSION,
        "environment": settings.app_env,
        "timestamp": datetime.now(UTC).isoformat(),
        "frontend_url": settings.frontend_url,
        "project_ref": project_ref_from_url(settings.supabase_url_normalized),
        "checks": checks,
        "endpoints": {
            "ping": "/api/status/ping",
            "ready": "/api/status/ready",
            "health": "/health",
            "db_check": "/api/tests/db-check",
            "r2_check": "/api/tests/r2-check",
            "google_authorize": "/auth/google/authorize?next=/dashboard",
            "docs": "/docs",
        },
        "config": diag,
    }


@router.get("/ready")
def readiness() -> dict[str, object]:
    """Readiness — API + Supabase must respond. Returns 503 when DB is unreachable."""
    settings = get_settings()
    host_status, hint = probe_supabase(
        settings.supabase_url_normalized,
        settings.supabase_secret_key,
    )
    if host_status != "reachable":
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "service": SERVICE,
                "supabase": host_status,
                "hint": hint,
                "project_ref": project_ref_from_url(settings.supabase_url_normalized),
            },
        )
    return {
        "status": "ready",
        "service": SERVICE,
        "supabase": "reachable",
        "redis": redis_status(),
        "google_oauth": _google_oauth_state(),
    }
