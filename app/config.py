import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _resolve_bind_port(default: int = 8000) -> int:
    """Railway PORT → API_PORT → default. Empty strings are ignored.

    Prefer PORT so a Dockerfile/local API_PORT default cannot shadow Railway.
    """
    for key in ("PORT", "API_PORT"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return int(raw)
    return default

# Always load backend/.env regardless of shell cwd (e.g. uvicorn started from repo root).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"
_ENV_LOCAL_FILE = _BACKEND_DIR / ".env.local"


def _env_files() -> tuple[str, ...]:
    """`.env.local` overrides `.env` in dev only (never in production / Docker prod)."""
    paths: list[Path] = [_ENV_FILE]
    app_env = os.environ.get("APP_ENV", "development").strip().lower()
    if app_env != "production" and _ENV_LOCAL_FILE.is_file():
        paths.append(_ENV_LOCAL_FILE)
    return tuple(str(p) for p in paths)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        env_file_override=True,
    )

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    enable_api_docs: bool = Field(
        default=False,
        validation_alias="ENABLE_API_DOCS",
        description="When true, expose /docs in production. Ignored in non-production (docs always on).",
    )
    trust_x_forwarded_for: bool = Field(
        default=False,
        validation_alias="TRUST_X_FORWARDED_FOR",
        description="When true, use rightmost X-Forwarded-For hop; otherwise request.client.host.",
    )

    supabase_url: str = Field(
        validation_alias=AliasChoices("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"),
    )
    supabase_secret_key: str = Field(
        validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )

    jwt_secret: str = Field(
        default="dev-jwt-secret-change-in-production",
        validation_alias="JWT_SECRET",
    )
    jwt_refresh_secret: str = Field(
        default="dev-jwt-refresh-secret-change-in-production",
        validation_alias="JWT_REFRESH_SECRET",
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(
        default=15, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    refresh_token_expire_days: int = Field(
        default=30, validation_alias="REFRESH_TOKEN_EXPIRE_DAYS"
    )

    frontend_url: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("FRONTEND_URL", "NEXT_PUBLIC_APP_URL"),
    )
    cors_origins: str = Field(
        default="",
        validation_alias="CORS_ORIGINS",
        description="Comma-separated extra browser origins (production Vercel, staging).",
    )

    redis_url: str = Field(default="", validation_alias="REDIS_URL")

    # Rate limiting — None means auto (fail-closed in production when REDIS_URL is set).
    rate_limit_fail_closed: bool | None = Field(
        default=None,
        validation_alias="RATE_LIMIT_FAIL_CLOSED",
        description="When true, Redis outage returns 503 instead of memory fallback.",
    )
    rate_limit_login: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_LOGIN"
    )
    rate_limit_create_order: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_CREATE_ORDER"
    )
    rate_limit_verify: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_VERIFY"
    )
    rate_limit_register: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_REGISTER"
    )
    rate_limit_forgot_password: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_FORGOT_PASSWORD"
    )
    rate_limit_collect_lead: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_COLLECT_LEAD"
    )
    rate_limit_guest_session: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_GUEST_SESSION"
    )
    rate_limit_submit_review: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_SUBMIT_REVIEW"
    )
    rate_limit_evaluate_writing: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_EVALUATE_WRITING"
    )
    rate_limit_ai_writing_submit: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_AI_WRITING_SUBMIT"
    )
    rate_limit_ai_speaking_submit: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_AI_SPEAKING_SUBMIT"
    )
    rate_limit_ai_tutor_chat: int | None = Field(
        default=None, validation_alias="RATE_LIMIT_AI_TUTOR_CHAT"
    )

    msg91_auth_key: str = Field(default="", validation_alias="MSG91_AUTH_KEY")
    msg91_template_id: str = Field(default="", validation_alias="MSG91_TEMPLATE_ID")

    resend_api_key: str = Field(default="", validation_alias="RESEND_API_KEY")
    email_from: str = Field(
        default="BandForge <onboarding@resend.dev>",
        validation_alias="EMAIL_FROM",
    )
    notification_worker_batch_size: int = Field(
        default=20, validation_alias="NOTIFICATION_WORKER_BATCH_SIZE"
    )
    notification_worker_concurrency: int = Field(
        default=5, validation_alias="NOTIFICATION_WORKER_CONCURRENCY"
    )
    notification_worker_lease_seconds: int = Field(
        default=120, validation_alias="NOTIFICATION_WORKER_LEASE_SECONDS"
    )
    notification_worker_poll_seconds: float = Field(
        default=2.0, validation_alias="NOTIFICATION_WORKER_POLL_SECONDS"
    )
    meta_whatsapp_enabled: bool = Field(
        default=False, validation_alias="META_WHATSAPP_ENABLED"
    )
    meta_whatsapp_graph_version: str = Field(
        default="v23.0", validation_alias="META_WHATSAPP_GRAPH_VERSION"
    )
    meta_whatsapp_phone_number_id: str = Field(
        default="", validation_alias="META_WHATSAPP_PHONE_NUMBER_ID"
    )
    meta_whatsapp_access_token: str = Field(
        default="", validation_alias="META_WHATSAPP_ACCESS_TOKEN"
    )
    meta_whatsapp_template_name: str = Field(
        default="", validation_alias="META_WHATSAPP_TEMPLATE_NAME"
    )
    meta_whatsapp_template_language: str = Field(
        default="en", validation_alias="META_WHATSAPP_TEMPLATE_LANGUAGE"
    )
    meta_whatsapp_verify_token: str = Field(
        default="", validation_alias="META_WHATSAPP_VERIFY_TOKEN"
    )
    meta_whatsapp_app_secret: str = Field(
        default="", validation_alias="META_WHATSAPP_APP_SECRET"
    )

    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", validation_alias="OPENAI_MODEL")
    openai_whisper_model: str = Field(
        default="whisper-1",
        validation_alias="OPENAI_WHISPER_MODEL",
    )

    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
    )
    anthropic_aws_api_key: str = Field(
        default="",
        validation_alias="ANTHROPIC_AWS_API_KEY",
    )
    anthropic_aws_workspace_id: str = Field(
        default="",
        validation_alias="ANTHROPIC_AWS_WORKSPACE_ID",
    )
    aws_region: str = Field(
        default="eu-north-1",
        validation_alias=AliasChoices("AWS_REGION", "AWS_DEFAULT_REGION"),
    )
    anthropic_provider: str = Field(
        default="auto",
        validation_alias="ANTHROPIC_PROVIDER",
        description="auto | direct | aws — auto prefers Claude Platform on AWS when ANTHROPIC_AWS_API_KEY is set.",
    )
    anthropic_model: str = Field(
        default="claude-sonnet-4-6",
        validation_alias="ANTHROPIC_MODEL",
    )

    speaking_eval_stub: bool = Field(
        default=False,
        validation_alias="SPEAKING_EVAL_STUB",
    )
    writing_eval_stub: bool = Field(
        default=False,
        validation_alias="WRITING_EVAL_STUB",
    )
    speaking_eval_timeout_sec: int = Field(
        default=120,
        validation_alias="SPEAKING_EVAL_TIMEOUT_SEC",
    )
    writing_eval_timeout_sec: int = Field(
        default=120,
        validation_alias="WRITING_EVAL_TIMEOUT_SEC",
    )
    asr_provider: str = Field(
        default="openai",
        validation_alias="ASR_PROVIDER",
    )
    llm_provider: str = Field(
        default="claude",
        validation_alias="LLM_PROVIDER",
    )
    speaking_llm_fallback: str = Field(
        default="groq",
        validation_alias="SPEAKING_LLM_FALLBACK",
    )
    writing_llm_primary: str = Field(
        default="claude",
        validation_alias="WRITING_LLM_PRIMARY",
    )
    writing_llm_fallback: str = Field(
        default="groq",
        validation_alias="WRITING_LLM_FALLBACK",
    )

    # Phase 3 — AI ops (budget, circuit, cost estimate)
    claude_daily_limit: int = Field(default=200, validation_alias="CLAUDE_DAILY_LIMIT")
    claude_monthly_limit: int = Field(
        default=2000, validation_alias="CLAUDE_MONTHLY_LIMIT"
    )
    claude_warning_at: int = Field(
        default=0,
        validation_alias="CLAUDE_WARNING_AT",
        description="Warn when daily Claude evals reach this count (0 = 80% of daily limit).",
    )
    groq_daily_limit: int = Field(default=500, validation_alias="GROQ_DAILY_LIMIT")
    groq_monthly_limit: int = Field(
        default=5000, validation_alias="GROQ_MONTHLY_LIMIT"
    )
    groq_warning_at: int = Field(
        default=0,
        validation_alias="GROQ_WARNING_AT",
        description="Warn when daily Groq evals reach this count (0 = 80% of daily limit).",
    )
    ai_circuit_fail_threshold: int = Field(
        default=5, validation_alias="AI_CIRCUIT_FAIL_THRESHOLD"
    )
    ai_circuit_cooldown_sec: int = Field(
        default=300, validation_alias="AI_CIRCUIT_COOLDOWN_SEC"
    )
    ai_budget_fallback_stub: bool = Field(
        default=True, validation_alias="AI_BUDGET_FALLBACK_STUB"
    )
    ai_input_usd_per_mtok: float = Field(
        default=3.0, validation_alias="AI_INPUT_USD_PER_MTOK"
    )
    ai_output_usd_per_mtok: float = Field(
        default=15.0, validation_alias="AI_OUTPUT_USD_PER_MTOK"
    )

    groq_api_key: str = Field(default="", validation_alias="GROQ_API_KEY")
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        validation_alias="GROQ_MODEL",
    )
    groq_whisper_model: str = Field(
        default="whisper-large-v3-turbo",
        validation_alias="GROQ_WHISPER_MODEL",
    )
    groq_api_base: str = Field(
        default="https://api.groq.com/openai/v1",
        validation_alias="GROQ_API_BASE",
    )
    writing_prompt_version: str = Field(
        default="v5",
        validation_alias=AliasChoices(
            "WRITING_PROMPT_VERSION",
            "DIAGNOSTIC_WRITING_PROMPT_VERSION",
        ),
    )

    razorpay_key_id: str = Field(default="", validation_alias="RAZORPAY_KEY_ID")
    razorpay_key_secret: str = Field(default="", validation_alias="RAZORPAY_KEY_SECRET")
    razorpay_webhook_secret: str = Field(
        default="", validation_alias="RAZORPAY_WEBHOOK_SECRET"
    )
    razorpay_enabled: bool = Field(default=False, validation_alias="RAZORPAY_ENABLED")
    razorpay_checkout_config_id: str = Field(
        default="", validation_alias="RAZORPAY_CHECKOUT_CONFIG_ID"
    )

    auth_demo_otp: str = Field(default="", validation_alias="AUTH_DEMO_OTP")
    auth_open_otp: bool = Field(default=False, validation_alias="AUTH_OPEN_OTP")
    auth_demo_otp_enabled: bool = Field(
        default=False, validation_alias="AUTH_DEMO_OTP_ENABLED"
    )
    phone_otp_enabled: bool = Field(
        default=False, validation_alias="PHONE_OTP_ENABLED"
    )
    auth_skip_email_verify: bool = Field(
        default=False,
        validation_alias="AUTH_SKIP_EMAIL_VERIFY",
    )

    admin_allowed_email: str = Field(
        default="",
        validation_alias="ADMIN_ALLOWED_EMAIL",
        description="Only this email may access /admin (fail-closed if unset).",
    )

    google_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_CLIENT_ID", "google_client_id"),
    )
    google_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_CLIENT_SECRET", "google_client_secret"),
    )
    google_redirect_uri: str = Field(
        default="http://localhost:3000/api/auth/google/callback",
        validation_alias=AliasChoices("GOOGLE_REDIRECT_URI", "google_redirect_uri"),
    )

    @field_validator(
        "auth_open_otp",
        "auth_demo_otp_enabled",
        "phone_otp_enabled",
        "auth_skip_email_verify",
        "razorpay_enabled",
        "speaking_eval_stub",
        "writing_eval_stub",
        "ai_budget_fallback_stub",
        "meta_whatsapp_enabled",
        "enable_api_docs",
        "trust_x_forwarded_for",
        mode="before",
    )
    @classmethod
    def parse_bool_fields(cls, v: object) -> bool:
        return _env_bool(v)

    @field_validator("rate_limit_fail_closed", mode="before")
    @classmethod
    def parse_optional_bool(cls, v: object) -> bool | None:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return _env_bool(v)

    @field_validator(
        "google_client_id",
        "google_client_secret",
        "google_redirect_uri",
        "resend_api_key",
        "meta_whatsapp_access_token",
        "meta_whatsapp_verify_token",
        "meta_whatsapp_app_secret",
        "openai_api_key",
        "anthropic_api_key",
        "anthropic_aws_api_key",
        "anthropic_aws_workspace_id",
        "aws_region",
        "groq_api_key",
        "razorpay_key_id",
        "razorpay_key_secret",
        "razorpay_webhook_secret",
        "cloudflare_api_token",
        mode="before",
    )
    @classmethod
    def strip_secrets(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "bandforge-speaking-audio"
    r2_endpoint_url: str = ""

    # Cloudflare API token (Stream Edit) — separate from R2 S3 keys
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""

    # Cloudflare Stream playback (customer subdomain without .cloudflarestream.com)
    stream_customer_code: str = ""
    stream_signing_key_id: str = ""
    stream_signing_key_jwk: str = ""
    stream_token_ttl_seconds: int = 3600
    practice_lock_public_videos: bool = True

    api_host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("API_HOST", "api_host"),
    )
    api_port: int = Field(
        default=8000,
        validation_alias=AliasChoices("PORT", "API_PORT", "api_port"),
    )

    @field_validator("api_port", mode="before")
    @classmethod
    def parse_api_port(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            return _resolve_bind_port()
        if isinstance(v, str):
            stripped = v.strip()
            return int(stripped) if stripped else _resolve_bind_port()
        return v

    @property
    def supabase_url_normalized(self) -> str:
        return self.supabase_url.rstrip("/")

    def admin_allowed_email_normalized(self) -> str | None:
        email = self.admin_allowed_email.strip().lower()
        return email or None

    def cors_allow_origins(self) -> list[str]:
        """Origins for CORSMiddleware (frontend + optional CORS_ORIGINS + localhost in dev)."""
        origins: list[str] = []
        for raw in (self.frontend_url, self.cors_origins):
            for part in raw.split(","):
                origin = part.strip().rstrip("/")
                if origin and origin not in origins:
                    origins.append(origin)
        if self.app_env.strip().lower() != "production":
            for local in (
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:3001",
                "http://127.0.0.1:3001",
            ):
                if local not in origins:
                    origins.append(local)
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=_env_files())


def reload_settings() -> Settings:
    """Clear cached settings/client after .env changes (dev convenience)."""
    get_settings.cache_clear()
    from app.db.supabase_client import get_supabase
    from app.config import reload_settings
    from app.payments.razorpay_client import clear_client_cache, clear_credentials_probe

    get_supabase.cache_clear()
    clear_client_cache()
    clear_credentials_probe()
    return get_settings()


def settings_diagnostics() -> dict[str, str]:
    from app.supabase_probe import project_ref_from_url

    s = get_settings()
    local = _ENV_LOCAL_FILE.is_file()
    return {
        "env_file": str(_ENV_FILE),
        "env_file_exists": str(_ENV_FILE.is_file()),
        "env_local": str(_ENV_LOCAL_FILE) if local else "",
        "env_local_active": str(local),
        "project_ref": project_ref_from_url(s.supabase_url_normalized),
        "supabase_url": s.supabase_url_normalized,
    }


def razorpay_env_diagnostics() -> dict[str, str]:
    """Non-secret Razorpay config diagnostics for startup logs."""
    s = get_settings()
    kid = s.razorpay_key_id or ""
    shell_kid = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    shell_secret_set = bool(os.environ.get("RAZORPAY_KEY_SECRET", "").strip())
    mode = (
        "TEST"
        if kid.startswith("rzp_test_")
        else "LIVE"
        if kid.startswith("rzp_live_")
        else "UNSET"
    )
    shell_override = ""
    if shell_kid and shell_kid != kid:
        shell_override = (
            "shell RAZORPAY_KEY_ID differs from loaded settings "
            "(env_file_override should prefer .env — restart in a clean shell if this persists)"
        )
    elif shell_kid and shell_secret_set and not kid:
        shell_override = "shell has RAZORPAY_* but settings loaded empty key"
    return {
        "mode": mode,
        "key_id_prefix": f"{kid[:18]}..." if kid else "(unset)",
        "shell_key_id_set": str(bool(shell_kid)),
        "shell_secret_set": str(shell_secret_set),
        "shell_override_warning": shell_override,
    }
