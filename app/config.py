from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load backend/.env regardless of shell cwd (e.g. uvicorn started from repo root).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str = Field(
        validation_alias=AliasChoices("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"),
    )
    supabase_secret_key: str = Field(
        validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )

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
