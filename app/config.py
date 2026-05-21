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

# Always load backend/.env regardless of shell cwd (e.g. uvicorn started from repo root).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", validation_alias="APP_ENV")

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

    redis_url: str = Field(default="", validation_alias="REDIS_URL")

    msg91_auth_key: str = Field(default="", validation_alias="MSG91_AUTH_KEY")
    msg91_template_id: str = Field(default="", validation_alias="MSG91_TEMPLATE_ID")

    resend_api_key: str = Field(default="", validation_alias="RESEND_API_KEY")
    email_from: str = Field(
        default="BandForge <onboarding@resend.dev>",
        validation_alias="EMAIL_FROM",
    )

    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", validation_alias="OPENAI_MODEL")

    auth_demo_otp: str = Field(default="", validation_alias="AUTH_DEMO_OTP")
    auth_open_otp: bool = Field(default=False, validation_alias="AUTH_OPEN_OTP")
    auth_demo_otp_enabled: bool = Field(
        default=True, validation_alias="AUTH_DEMO_OTP_ENABLED"
    )
    phone_otp_enabled: bool = Field(
        default=False, validation_alias="PHONE_OTP_ENABLED"
    )
    auth_skip_email_verify: bool = Field(
        default=True,
        validation_alias="AUTH_SKIP_EMAIL_VERIFY",
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
        mode="before",
    )
    @classmethod
    def parse_bool_fields(cls, v: object) -> bool:
        return _env_bool(v)

    @field_validator(
        "google_client_id",
        "google_client_secret",
        "google_redirect_uri",
        "resend_api_key",
        "openai_api_key",
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

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @property
    def supabase_url_normalized(self) -> str:
        return self.supabase_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Clear cached settings/client after .env changes (dev convenience)."""
    get_settings.cache_clear()
    from app.db.supabase_client import get_supabase

    get_supabase.cache_clear()
    return get_settings()


def settings_diagnostics() -> dict[str, str]:
    from app.supabase_probe import project_ref_from_url

    s = get_settings()
    return {
        "env_file": str(_ENV_FILE),
        "env_file_exists": str(_ENV_FILE.is_file()),
        "project_ref": project_ref_from_url(s.supabase_url_normalized),
        "supabase_url": s.supabase_url_normalized,
    }
