"""Unit tests for otp_demo_mode()."""

from unittest.mock import MagicMock, patch

from app.auth.demo_mode import otp_demo_mode


def test_otp_demo_mode_false_in_production():
    settings = MagicMock(
        app_env="production",
        auth_demo_otp_enabled=True,
        auth_open_otp=True,
        auth_demo_otp="123456",
    )
    with patch("app.auth.demo_mode.get_settings", return_value=settings):
        assert otp_demo_mode() is False


def test_otp_demo_mode_false_when_flags_off_in_development():
    settings = MagicMock(
        app_env="development",
        auth_demo_otp_enabled=False,
        auth_open_otp=False,
        auth_demo_otp="",
    )
    with patch("app.auth.demo_mode.get_settings", return_value=settings):
        assert otp_demo_mode() is False


def test_otp_demo_mode_true_when_auth_demo_otp_set():
    settings = MagicMock(
        app_env="development",
        auth_demo_otp_enabled=False,
        auth_open_otp=False,
        auth_demo_otp="123456",
    )
    with patch("app.auth.demo_mode.get_settings", return_value=settings):
        assert otp_demo_mode() is True


def test_otp_demo_mode_true_when_demo_enabled_flag():
    settings = MagicMock(
        app_env="development",
        auth_demo_otp_enabled=True,
        auth_open_otp=False,
        auth_demo_otp="",
    )
    with patch("app.auth.demo_mode.get_settings", return_value=settings):
        assert otp_demo_mode() is True
