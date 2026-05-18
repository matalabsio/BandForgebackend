from fastapi import APIRouter, HTTPException

from app.config import get_settings, settings_diagnostics
from app.db.supabase_client import get_supabase
from app.storage.r2_check import run_r2_check
from app.supabase_probe import probe_supabase, project_ref_from_url

router = APIRouter(prefix="/api/tests", tags=["tests"])

PHASE2_TABLES = (
    "questions",
    "test_attempts",
    "answers",
    "module_scores",
    "speaking_reviews",
)

DNS_MARKERS = ("nodename nor servname", "Name or service not known", "NXDOMAIN", "Cannot reach")


def _classify_table_error(exc: Exception) -> str:
    msg = str(exc)
    if any(m in msg for m in DNS_MARKERS):
        return "dns_error"
    if "403" in msg or "401" in msg:
        return "auth_error"
    if "404" in msg or "PGRST205" in msg or "does not exist" in msg.lower():
        return "table_missing"
    return "error"


@router.get("/health")
def tests_health() -> dict[str, str]:
    """Router-level health check (full app health is GET /health)."""
    return {"status": "ok", "router": "tests"}


@router.get("/db-check")
def db_check() -> dict[str, object]:
    """Postman-friendly Supabase + Phase 2 table probe (no frontend required)."""
    settings = get_settings()
    diag = settings_diagnostics()
    host_status, host_hint = probe_supabase(
        settings.supabase_url_normalized,
        settings.supabase_secret_key,
    )

    if host_status == "auth_error":
        raise HTTPException(
            status_code=503,
            detail={
                "api": "ok",
                "supabase_host": host_status,
                "supabase_url": settings.supabase_url_normalized,
                "project_ref": project_ref_from_url(settings.supabase_url_normalized),
                "config": diag,
                "hint": host_hint,
                "note": (
                    "MCP (.cursor/mcp.json) only configures Cursor — this endpoint uses backend/.env. "
                    "Restart uvicorn after editing .env."
                ),
            },
        )

    if host_status not in ("reachable",):
        raise HTTPException(
            status_code=503,
            detail={
                "api": "ok",
                "supabase_host": host_status,
                "supabase_url": settings.supabase_url_normalized,
                "project_ref": project_ref_from_url(settings.supabase_url_normalized),
                "config": diag,
                "hint": host_hint,
                "note": (
                    "MCP (.cursor/mcp.json) only configures Cursor — this endpoint uses backend/.env. "
                    "Restart uvicorn after editing .env."
                ),
            },
        )

    client = get_supabase()
    tables: dict[str, str] = {}
    error_kinds: set[str] = set()

    for table in PHASE2_TABLES:
        try:
            client.table(table).select("id").limit(1).execute()
            tables[table] = "ok"
        except Exception as exc:  # noqa: BLE001 — surfaced to API consumer
            kind = _classify_table_error(exc)
            error_kinds.add(kind)
            tables[table] = f"{kind}: {exc}"

    if error_kinds:
        hints: list[str] = []
        if "dns_error" in error_kinds:
            hints.append("Fix NEXT_PUBLIC_SUPABASE_URL in backend/.env (Dashboard → Settings → API).")
        if "auth_error" in error_kinds:
            hints.append("Use SUPABASE_SECRET_KEY (secret / service role), not the publishable key.")
        if "table_missing" in error_kinds:
            hints.append("Run supabase/migrations/20260518120000_phase2_new_tables.sql in SQL Editor.")

        raise HTTPException(
            status_code=503,
            detail={
                "api": "ok",
                "supabase_host": "reachable",
                "tables": tables,
                "hint": " ".join(hints) or "See table errors above.",
            },
        )

    return {
        "api": "ok",
        "supabase_host": "reachable",
        "project_ref": project_ref_from_url(settings.supabase_url_normalized),
        "config": diag,
        "tables": tables,
    }


@router.get("/r2-check")
def r2_check() -> dict[str, object]:
    """Postman-friendly R2 upload + presigned URL probe."""
    result = run_r2_check()
    ok = (
        result.get("r2_configured")
        and result.get("upload_ok")
        and result.get("signed_url_ok")
    )
    if not ok:
        raise HTTPException(
            status_code=503,
            detail={"api": "ok", **result},
        )
    return {"api": "ok", **result}
