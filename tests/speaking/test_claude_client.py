"""Tests for Claude client auth resolution."""

from __future__ import annotations

from unittest.mock import patch

from app.speaking.claude_client import (
    claude_configuration_error,
    claude_configured,
    resolve_claude_auth_mode,
)


def test_claude_configured_direct_api_key():
    with patch("app.speaking.claude_client.get_settings") as settings:
        settings.return_value.anthropic_provider = "auto"
        settings.return_value.anthropic_api_key = "sk-ant-test"
        settings.return_value.anthropic_aws_api_key = ""
        settings.return_value.anthropic_aws_workspace_id = ""
        assert resolve_claude_auth_mode() == "direct"
        assert claude_configured() is True


def test_claude_configured_aws_platform():
    with patch("app.speaking.claude_client.get_settings") as settings:
        settings.return_value.anthropic_provider = "aws"
        settings.return_value.anthropic_api_key = ""
        settings.return_value.anthropic_aws_api_key = "aws-external-anthropic-api-key-test"
        settings.return_value.anthropic_aws_workspace_id = "ws_123"
        assert resolve_claude_auth_mode() == "aws"
        assert claude_configured() is True


def test_aws_key_without_workspace_reports_error():
    with patch("app.speaking.claude_client.get_settings") as settings:
        settings.return_value.anthropic_provider = "auto"
        settings.return_value.anthropic_api_key = ""
        settings.return_value.anthropic_aws_api_key = "aws-external-anthropic-api-key-test"
        settings.return_value.anthropic_aws_workspace_id = ""
        assert resolve_claude_auth_mode() is None
        assert claude_configured() is False
        assert "WORKSPACE_ID" in (claude_configuration_error() or "")
