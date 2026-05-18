"""Supabase reachability checks (uses supabase-py — same stack as the API client)."""

from urllib.parse import urlparse

from supabase import create_client

PLACEHOLDER_HOSTS = ("your-project.supabase.co",)
DNS_MARKERS = (
    "nodename nor servname",
    "Name or service not known",
    "NXDOMAIN",
    "Cannot resolve",
    "getaddrinfo failed",
)


def project_ref_from_url(url: str) -> str:
    host = urlparse(url).hostname or ""
    if host.endswith(".supabase.co"):
        return host[: -len(".supabase.co")]
    return host


def is_valid_supabase_api_key(key: str) -> bool:
    """Reject DB passwords and other non-API values pasted into SUPABASE_SECRET_KEY."""
    key = key.strip()
    if not key or " " in key:
        return False
    return key.startswith(("eyJ", "sb_secret_", "sb_publishable_"))


def probe_supabase(url: str, api_key: str) -> tuple[str, str | None]:
    """
    Returns (status, hint).
    status: reachable | invalid_config | dns_failed | auth_error | error
    """
    base = url.rstrip("/")
    host = urlparse(base).hostname or ""
    if not host or any(p in host for p in PLACEHOLDER_HOSTS):
        return (
            "invalid_config",
            "Supabase URL is missing or still the .env.example placeholder.",
        )

    if not is_valid_supabase_api_key(api_key):
        return (
            "auth_error",
            "SUPABASE_SECRET_KEY is not a Supabase API key (expected eyJ…, sb_secret_…, or "
            "sb_publishable_…). Copy **service_role** or **secret** from Dashboard → Settings → API. "
            "Do not use your database password.",
        )

    try:
        client = create_client(base, api_key)
        client.table("questions").select("id").limit(1).execute()
        return "reachable", None
    except Exception as exc:  # noqa: BLE001 — mapped to API hints
        msg = str(exc)
        if any(m in msg for m in DNS_MARKERS):
            return (
                "dns_failed",
                f"Cannot resolve '{host}'. Use the Project URL from Supabase Dashboard → "
                f"Settings → API (https://<project_ref>.supabase.co). "
                f"MCP project_ref should match backend/.env.",
            )
        if "Invalid API key" in msg:
            return (
                "auth_error",
                "SUPABASE_SECRET_KEY was rejected by Supabase. In Dashboard → Settings → API "
                "(project nkwtxkhtsclyakympbno), copy a fresh **secret** (sb_secret_…) or "
                "**service_role** (eyJ…) key into backend/.env — not the publishable key. "
                "Regenerate the secret key if it was rotated or copied from another project.",
            )
        if "403" in msg or "401" in msg or "JWT" in msg:
            return (
                "auth_error",
                "Supabase host is reachable but the API rejected the key. Use SUPABASE_SECRET_KEY "
                "(secret or service_role from Dashboard → Settings → API), not the publishable key.",
            )
        if "404" in msg or "PGRST205" in msg:
            return "reachable", None
        return "error", msg[:300]
