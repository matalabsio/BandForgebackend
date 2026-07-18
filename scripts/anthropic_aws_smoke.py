#!/usr/bin/env python3
"""Smoke-test Claude via Claude Platform on AWS (ANTHROPIC_AWS_API_KEY)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, reload_settings
from app.speaking.claude_client import (
    chat_completion_json,
    claude_configuration_error,
    claude_configured,
    discover_aws_workspaces,
    resolve_claude_auth_mode,
)


async def _discover() -> int:
    try:
        workspaces = await discover_aws_workspaces()
    except Exception as exc:
        print(f"FAIL  {exc}")
        return 1

    if not workspaces:
        print("FAIL  No workspaces returned. Check IAM permissions or AWS Console.")
        return 1

    print("OK    workspaces found:")
    for ws in workspaces:
        ws_id = ws.get("id", "")
        name = ws.get("name", "(unnamed)")
        print(f"      {ws_id}  {name}")
    print()
    print("Add to backend/.env.local:")
    print(f"ANTHROPIC_AWS_WORKSPACE_ID={workspaces[0].get('id', '')}")
    return 0


async def _run() -> int:
    settings = get_settings()
    mode = resolve_claude_auth_mode()
    print(f"  ANTHROPIC_PROVIDER={settings.anthropic_provider}")
    print(f"  AWS_REGION={settings.aws_region}")
    print(f"  auth_mode={mode}")
    print(f"  workspace_id_set={bool(settings.anthropic_aws_workspace_id.strip())}")
    print(f"  aws_api_key_set={bool(settings.anthropic_aws_api_key.strip())}")
    print(f"  direct_api_key_set={bool(settings.anthropic_api_key.strip())}")
    print(f"  model={settings.anthropic_model}")

    if not claude_configured():
        print(f"FAIL  {claude_configuration_error()}")
        if settings.anthropic_aws_api_key.strip() and not settings.anthropic_aws_workspace_id.strip():
            print("HINT  Try: python scripts/anthropic_aws_smoke.py --discover-workspaces --reload-env")
        return 1

    try:
        text, raw = await chat_completion_json(
            system="Reply with one word only.",
            user="Say hello.",
            max_tokens=32,
        )
    except Exception as exc:
        print(f"FAIL  {exc}")
        return 1

    print(f"OK    provider={raw.get('_bandforge_auth_mode')} response={text!r}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Platform on AWS smoke test")
    parser.add_argument("--reload-env", action="store_true")
    parser.add_argument(
        "--discover-workspaces",
        action="store_true",
        help="List wrkspc_ IDs from Claude Platform on AWS (needs API key only)",
    )
    args = parser.parse_args()
    if args.reload_env:
        reload_settings()
    if args.discover_workspaces:
        return asyncio.run(_discover())
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
