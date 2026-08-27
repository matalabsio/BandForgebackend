"""Staging environment isolation guards."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.env_safety import (
    PRODUCTION_RAILWAY_API_HOST,
    PRODUCTION_SUPABASE_PROJECT_REF,
    assert_environment_safety,
)


def _settings(**overrides):
    base = dict(
        app_env="staging",
        supabase_url=f"https://stagingprojectref123.supabase.co",
        supabase_url_normalized="https://stagingprojectref123.supabase.co",
        frontend_url="https://staging.example.com",
        google_redirect_uri="https://staging.example.com/api/auth/google/callback",
        public_api_url="https://staging-api.example.com",
        razorpay_enabled=True,
        razorpay_key_id="rzp_test_examplekey",
        razorpay_key_secret="test_secret",
        razorpay_webhook_secret="whsec_test",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_staging_allows_isolated_configuration():
    assert_environment_safety(_settings())


def test_non_staging_is_noop_even_with_production_supabase():
    assert_environment_safety(
        _settings(
            app_env="production",
            supabase_url=f"https://{PRODUCTION_SUPABASE_PROJECT_REF}.supabase.co",
            supabase_url_normalized=(
                f"https://{PRODUCTION_SUPABASE_PROJECT_REF}.supabase.co"
            ),
            razorpay_enabled=False,
        )
    )
    assert_environment_safety(
        _settings(
            app_env="development",
            supabase_url=f"https://{PRODUCTION_SUPABASE_PROJECT_REF}.supabase.co",
            supabase_url_normalized=(
                f"https://{PRODUCTION_SUPABASE_PROJECT_REF}.supabase.co"
            ),
            razorpay_enabled=False,
        )
    )


def test_staging_rejects_production_supabase_project():
    with pytest.raises(RuntimeError, match="production Supabase"):
        assert_environment_safety(
            _settings(
                supabase_url=f"https://{PRODUCTION_SUPABASE_PROJECT_REF}.supabase.co",
                supabase_url_normalized=(
                    f"https://{PRODUCTION_SUPABASE_PROJECT_REF}.supabase.co"
                ),
            )
        )


def test_staging_rejects_production_frontend_host():
    with pytest.raises(RuntimeError, match="FRONTEND_URL"):
        assert_environment_safety(
            _settings(frontend_url="https://bandforgeuinew.vercel.app")
        )


def test_staging_rejects_live_razorpay_keys():
    with pytest.raises(RuntimeError, match="LIVE"):
        assert_environment_safety(
            _settings(razorpay_key_id="rzp_live_examplekey")
        )


def test_staging_rejects_missing_webhook_secret_when_payments_enabled():
    with pytest.raises(RuntimeError, match="RAZORPAY_WEBHOOK_SECRET"):
        assert_environment_safety(_settings(razorpay_webhook_secret=""))


def test_staging_rejects_production_public_api_host():
    with pytest.raises(RuntimeError, match="PUBLIC_API_URL"):
        assert_environment_safety(
            _settings(public_api_url=f"https://{PRODUCTION_RAILWAY_API_HOST}")
        )


def test_staging_example_file_documents_app_env():
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1]
        / "railway.staging.env.example"
    ).read_text()
    assert "APP_ENV=staging" in text
    assert "SUPABASE_URL=" in text
    assert "RAZORPAY_KEY_ID=rzp_test_" in text
    assert "nkwtxkhtsclyakympbno" in text  # documented as forbidden
    assert "YOUR_STAGING" in text
