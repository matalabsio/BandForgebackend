from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import get_settings, razorpay_env_diagnostics, reload_settings, settings_diagnostics
from app.cache.hybrid_cache import redis_status
from app.middleware.timing import ApiTimingMiddleware
from app.admin import router as admin_router
from app.auth import router as auth_router
from app.listening import router as listening_router
from app.learning import router as learning_router
from app.practice import router as practice_router
from app.tutor import router as tutor_router
from app.payments import router as payments_router
from app.reading import router as reading_router
from app.speaking.router import router as speaking_router
from app.notifications.router import router as notifications_router
from app.writing.router import router as writing_router
from app.routers import attempts, dashboard, diagnostic, marketing, mock_attempts, status, tests


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = reload_settings()
    diag = settings_diagnostics()
    google_ok = bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_redirect_uri
    )
    cors = settings.cors_allow_origins()
    print(
        f"[bandforge-api] Supabase project_ref={diag['project_ref']} "
        f"url={diag['supabase_url']} "
        f"env_local_active={diag['env_local_active']} "
        f"google_oauth={'on' if google_ok else 'off'} "
        f"frontend_url={settings.frontend_url} "
        f"admin_url={settings.admin_url} "
        f"cors_origins={','.join(cors) or '(none)'} "
        f"redis={redis_status()}"
    )
    if settings.app_env.strip().lower() == "production":
        if settings.auth_demo_otp_enabled:
            raise RuntimeError(
                "AUTH_DEMO_OTP_ENABLED must be false in production."
            )
        if settings.auth_open_otp:
            raise RuntimeError("AUTH_OPEN_OTP must be false in production.")
        if settings.auth_demo_otp:
            raise RuntimeError(
                "AUTH_DEMO_OTP must be unset in production."
            )
        if settings.auth_skip_email_verify:
            raise RuntimeError(
                "AUTH_SKIP_EMAIL_VERIFY must be false in production."
            )
        weak_jwt_defaults = (
            "dev-jwt-secret-change-in-production",
            "dev-jwt-refresh-secret-change-in-production",
        )
        for label, value in (
            ("JWT_SECRET", settings.jwt_secret),
            ("JWT_REFRESH_SECRET", settings.jwt_refresh_secret),
        ):
            secret = (value or "").strip()
            if (
                not secret
                or secret in weak_jwt_defaults
                or len(secret) < 32
            ):
                raise RuntimeError(
                    f"{label} is missing, uses a development default, or is shorter "
                    "than 32 characters. Set a strong secret before running in production."
                )
        if not settings.resend_api_key:
            detail = "RESEND_API_KEY is missing in production."
            if settings.email_otp_enabled:
                detail = (
                    "EMAIL_OTP_ENABLED is true but RESEND_API_KEY is missing."
                )
            raise RuntimeError(detail)
        if "onboarding@resend.dev" in settings.email_from.lower():
            raise RuntimeError(
                "EMAIL_FROM must use a verified production sender, not onboarding@resend.dev."
            )
        if settings.meta_whatsapp_enabled:
            required_meta = (
                ("META_WHATSAPP_PHONE_NUMBER_ID", settings.meta_whatsapp_phone_number_id),
                ("META_WHATSAPP_ACCESS_TOKEN", settings.meta_whatsapp_access_token),
                ("META_WHATSAPP_TEMPLATE_NAME", settings.meta_whatsapp_template_name),
                ("META_WHATSAPP_VERIFY_TOKEN", settings.meta_whatsapp_verify_token),
                ("META_WHATSAPP_APP_SECRET", settings.meta_whatsapp_app_secret),
            )
            missing_meta = [name for name, value in required_meta if not value]
            if missing_meta:
                raise RuntimeError(
                    "WhatsApp enabled in production but missing: "
                    + ", ".join(missing_meta)
                )
        for label, value in (
            ("FRONTEND_URL", settings.frontend_url),
            ("GOOGLE_REDIRECT_URI", settings.google_redirect_uri),
        ):
            if "localhost" in value or "127.0.0.1" in value:
                print(
                    f"[bandforge-api] WARNING: {label}={value!r} — "
                    "set production Vercel URL (see docs/vercel-production.md)"
                )
        if settings.razorpay_enabled:
            key_id = (settings.razorpay_key_id or "").strip()
            required: list[tuple[str, str]] = [
                ("RAZORPAY_KEY_ID", settings.razorpay_key_id),
                ("RAZORPAY_KEY_SECRET", settings.razorpay_key_secret),
            ]
            # Live keys must have webhook backup in production; Test mode can use /verify only.
            if key_id.startswith("rzp_live_"):
                required.append(
                    ("RAZORPAY_WEBHOOK_SECRET", settings.razorpay_webhook_secret)
                )
            missing = [name for name, val in required if not val]
            if missing:
                raise RuntimeError(
                    f"Payments enabled in production but missing: {', '.join(missing)}"
                )
            if key_id.startswith("rzp_test_") and not (
                settings.razorpay_webhook_secret or ""
            ).strip():
                print(
                    "[bandforge-api] WARNING: RAZORPAY_WEBHOOK_SECRET unset — "
                    "Test checkout works via /verify; set webhook secret for backup fulfillment"
                )
    elif settings.razorpay_enabled:
        missing = [
            name
            for name, val in (
                ("RAZORPAY_KEY_ID", settings.razorpay_key_id),
                ("RAZORPAY_KEY_SECRET", settings.razorpay_key_secret),
            )
            if not val
        ]
        if missing:
            print(
                f"[bandforge-api] WARNING: RAZORPAY_ENABLED but missing: {', '.join(missing)}"
            )
        if not settings.razorpay_webhook_secret:
            print(
                "[bandforge-api] WARNING: RAZORPAY_WEBHOOK_SECRET unset — "
                "webhook backup path disabled until configured"
            )
        if settings.razorpay_key_id and settings.razorpay_key_secret:
            rz_diag = razorpay_env_diagnostics()
            print(
                f"[bandforge-api] Razorpay config: mode={rz_diag['mode']} "
                f"key_id={rz_diag['key_id_prefix']}"
            )
            if rz_diag["shell_override_warning"]:
                print(f"[bandforge-api] WARNING: {rz_diag['shell_override_warning']}")

            from app.payments.razorpay_client import probe_credentials, set_credentials_probe_result

            ok, msg = probe_credentials()
            set_credentials_probe_result(ok)
            if ok:
                print("[bandforge-api] Razorpay credentials OK (API probe passed)")
            else:
                print(
                    f"[bandforge-api] ERROR: Razorpay auth failed — {msg}. "
                    "Regenerate matching API keys in Dashboard → Settings → API Keys."
                )
    yield


_settings = get_settings()
_is_prod = _settings.app_env.strip().lower() == "production"
_docs_enabled = (not _is_prod) or _settings.enable_api_docs

app = FastAPI(
    title="BandForge API",
    description="bandforge-api — test engine, evaluation, async jobs",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(ApiTimingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(status.router)
app.include_router(marketing.router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(tests.router)
app.include_router(attempts.router)
app.include_router(dashboard.router)
app.include_router(mock_attempts.router)
app.include_router(diagnostic.router)
app.include_router(listening_router)
app.include_router(reading_router)
app.include_router(writing_router)
app.include_router(speaking_router)
app.include_router(notifications_router)
app.include_router(payments_router)
app.include_router(learning_router)
app.include_router(practice_router)
app.include_router(tutor_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=True)
def root() -> str:
    """Browser-friendly landing page when visiting the API base URL."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BandForge API</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; padding: 0 1rem; color: #1c1917; }
    h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
    .ok { color: #047857; font-weight: 600; }
    ul { line-height: 1.8; }
    a { color: #0d9488; }
    code { background: #f5f5f4; padding: 0.1em 0.35em; border-radius: 4px; font-size: 0.9em; }
  </style>
</head>
<body>
  <h1>BandForge API</h1>
  <p class="ok">Python backend is running.</p>
  <p>FastAPI · bandforge-api (local)</p>
  <ul>
    <li><a href="/docs">Swagger UI</a> — <code>/docs</code></li>
    <li><a href="/health">Health</a> — <code>/health</code></li>
    <li><a href="/api/status">Status</a> — <code>/api/status</code></li>
    <li><a href="/api/status/ping">Ping</a> — <code>/api/status/ping</code></li>
    <li><a href="/api/status/ready">Ready</a> — <code>/api/status/ready</code></li>
    <li><a href="/api/tests/db-check">DB check</a> — <code>/api/tests/db-check</code></li>
    <li><a href="/api/tests/r2-check">R2 check</a> — <code>/api/tests/r2-check</code></li>
  </ul>
</body>
</html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
