"""Prompt version regression — v4 and v5 load and evaluate via stub."""

from __future__ import annotations

import asyncio

from app.diagnostic.writing_prompt import get_system_prompt, resolve_prompt_version
from app.writing.golden import load_golden_manifest
from app.writing.prompt_loader import load_writing_prompt
from app.writing.providers.factory import evaluate_writing_essay


def test_v4_and_v5_prompts_load_distinct():
    v4 = load_writing_prompt("v4")
    v5 = load_writing_prompt("v5")
    assert v4.version == "v4"
    assert v5.version == "v5"
    assert v4.system.strip()
    assert v5.system.strip()
    assert v4.system != v5.system
    assert "Academic" in v5.system
    assert "all Academic writing evaluations" in v5.system
    assert "Task 1 and Task 2" in v5.system
    assert "150" in v5.system
    assert "250" in v5.system
    assert "Task 2" in v5.system
    assert "General Training" in v5.system


def test_prompt_version_override_changes_resolve(monkeypatch):
    monkeypatch.setenv("WRITING_PROMPT_VERSION", "v4")
    from app.config import reload_settings

    reload_settings()
    assert resolve_prompt_version() == "v4"
    assert get_system_prompt() == load_writing_prompt("v4").system

    monkeypatch.setenv("WRITING_PROMPT_VERSION", "v5")
    reload_settings()
    assert resolve_prompt_version() == "v5"


def test_stub_eval_validates_under_v4_and_v5(monkeypatch):
    golden = load_golden_manifest()[0]

    async def eval_with(version: str):
        monkeypatch.setenv("WRITING_PROMPT_VERSION", version)
        monkeypatch.setenv("WRITING_EVAL_STUB", "true")
        from app.config import reload_settings

        reload_settings()
        result = await evaluate_writing_essay(
            task_part=golden.task_part,
            question=golden.question,
            essay=golden.essay,
        )
        assert result.prompt_version == version
        assert result.evaluation.overall_band >= 0
        return result.evaluation.overall_band

    band_v4 = asyncio.run(eval_with("v4"))
    band_v5 = asyncio.run(eval_with("v5"))
    # Stub ignores prompt text — bands match; both must simply validate.
    assert band_v4 == band_v5
