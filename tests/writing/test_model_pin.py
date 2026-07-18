"""Model / prompt pin and essay_hash isolation."""

from __future__ import annotations

import asyncio

from app.diagnostic.writing_prompt import resolve_prompt_version
from app.writing.eval_utils import compute_essay_hash, writing_cache_model_key
from app.writing.golden import load_golden_manifest
from app.writing.providers.constants import PROVIDER_NAME_STUB
from app.writing.providers.factory import evaluate_writing_essay


def test_essay_hash_changes_with_prompt_version():
    h1 = compute_essay_hash(
        task_part=2,
        question="Q",
        essay="Essay text",
        prompt_version="v4",
        model_name="m",
    )
    h2 = compute_essay_hash(
        task_part=2,
        question="Q",
        essay="Essay text",
        prompt_version="v5",
        model_name="m",
    )
    assert h1 != h2


def test_essay_hash_changes_with_model_name():
    h1 = compute_essay_hash(
        task_part=2,
        question="Q",
        essay="Essay text",
        prompt_version="v5",
        model_name="claude-a",
    )
    h2 = compute_essay_hash(
        task_part=2,
        question="Q",
        essay="Essay text",
        prompt_version="v5",
        model_name="claude-b",
    )
    assert h1 != h2


def test_essay_hash_stable_same_inputs():
    kwargs = dict(
        task_part=1,
        question="Q",
        essay="Essay text",
        prompt_version="v5",
        model_name="stub",
    )
    assert compute_essay_hash(**kwargs) == compute_essay_hash(**kwargs)


def test_stub_result_pins_prompt_and_model(monkeypatch):
    monkeypatch.setenv("WRITING_EVAL_STUB", "true")
    monkeypatch.setenv("WRITING_PROMPT_VERSION", "v5")
    from app.config import reload_settings

    reload_settings()
    golden = load_golden_manifest()[0]

    result = asyncio.run(
        evaluate_writing_essay(
            task_part=golden.task_part,
            question=golden.question,
            essay=golden.essay,
        )
    )
    assert result.prompt_version == resolve_prompt_version()
    assert result.prompt_version == "v5"
    assert result.model_name == PROVIDER_NAME_STUB
    assert writing_cache_model_key() == PROVIDER_NAME_STUB
