"""Tests for versioned writing prompt loader and Claude provider surface."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.diagnostic.writing_prompt import PROMPT_VERSION, SYSTEM_PROMPT
from app.writing.prompt_loader import PromptLoader, load_writing_prompt
from app.writing.providers.claude_eval import ClaudeProvider, ClaudeWritingProvider
from app.writing.providers.constants import PROVIDER_NAME_ANTHROPIC_CLAUDE
from app.writing.providers.factory import evaluate_writing_essay

VALID_ESSAY = " ".join(["word"] * 40)

VALID_EVAL_JSON = {
    "overall_band": 6.5,
    "task_achievement": 6.0,
    "coherence": 6.5,
    "lexical_resource": 7.0,
    "grammar": 6.0,
    "strengths": ["Clear overview"],
    "weaknesses": ["Limited comparison language"],
    "improvement_tips": ["Use more complex structures"],
    "spelling_mistakes": [],
    "grammar_mistakes": [],
    "spelling_error_count": 0,
}


def test_load_writing_prompt_v4():
    loaded = load_writing_prompt("v4")
    assert loaded.version == "v4"
    assert "IELTS Writing examiner" in loaded.system
    assert "overall_band" in loaded.system
    assert loaded.task1_rules is not None
    assert "overview" in loaded.task1_rules.lower()


def test_writing_prompt_module_matches_loader():
    loaded = load_writing_prompt(PROMPT_VERSION)
    assert SYSTEM_PROMPT.strip() == loaded.system.strip()
    assert PROMPT_VERSION == "v5"


def test_load_writing_prompt_v5():
    loaded = load_writing_prompt("v5")
    assert loaded.version == "v5"
    assert "all Academic writing evaluations" in loaded.system
    assert "Task 1 and Task 2" in loaded.system
    assert "Academic" in loaded.system
    assert "General Training" in loaded.system
    assert "150" in loaded.system
    assert "250" in loaded.system
    assert "Task 2" in loaded.system
    assert "next_band_advice" in loaded.system
    assert "vocabulary_highlights" in loaded.system
    assert "strong_spans" in loaded.system
    assert "confidence" in loaded.system
    assert "Target band" in loaded.system
    assert loaded.task1_rules is not None
    assert "150" in loaded.task1_rules
    assert "250" in loaded.task1_rules
    assert "Task 2" in loaded.task1_rules


def test_build_user_prompt_includes_task1_visual_and_metadata():
    from app.diagnostic.writing_prompt import build_user_prompt

    prompt = build_user_prompt(
        task_part=1,
        question="The bar chart shows transport modes.",
        essay="Overall, Tokyo had the highest share.",
        visual_description="Bars for car, bus, cycle, walk across four cities.",
        word_count=182,
        target_band=7.5,
    )
    assert "Task 1 (Academic)" in prompt
    assert "The bar chart shows transport modes." in prompt
    assert "Visual / chart description:" in prompt
    assert "Bars for car, bus, cycle, walk across four cities." in prompt
    assert "Student essay:" in prompt
    assert "Overall, Tokyo had the highest share." in prompt
    assert "Word count: 182" in prompt
    assert "Academic minimum for this task: 150 words" in prompt
    assert "Target band: 7.5" in prompt
    assert "Do not inflate criterion scores" in prompt
    assert "Return JSON only." in prompt


def test_build_user_prompt_omits_visual_for_task2():
    from app.diagnostic.writing_prompt import build_user_prompt

    prompt = build_user_prompt(
        task_part=2,
        question="Some people think governments should invest in public transport.",
        essay="Nowadays many people believe public transport matters.",
        visual_description="This should not appear for Task 2.",
        word_count=40,
        target_band=7.0,
    )
    assert "Task 2 (Academic)" in prompt
    assert "Visual / chart description:" not in prompt
    assert "This should not appear for Task 2." not in prompt
    assert "Word count: 40" in prompt
    assert "Academic minimum for this task: 250 words" in prompt
    assert "Target band: 7" in prompt


def test_compute_essay_hash_changes_with_visual_description():
    from app.writing.eval_utils import compute_essay_hash

    base = dict(task_part=1, question="Q", essay="Essay text")
    h1 = compute_essay_hash(**base, visual_description="")
    h2 = compute_essay_hash(**base, visual_description="Bar chart of four cities")
    assert h1 != h2
    assert h2 == compute_essay_hash(**base, visual_description="Bar chart of four cities")


def test_visual_description_from_task_options():
    from app.writing.eval_utils import visual_description_from_task_options

    text = visual_description_from_task_options(
        {
            "figure_label": "Figure 1",
            "figure_note": "Grouped bar chart of transport modes.",
            "chart": {
                "type": "bar",
                "title": "Commuter modes 2022",
                "cities": ["Tokyo", "Berlin"],
                "series": [{"label": "Car"}, {"label": "Bus"}],
            },
        },
        part=1,
    )
    assert "Figure 1" in text
    assert "Grouped bar chart" in text
    assert "Commuter modes 2022" in text
    assert "Tokyo" in text
    assert "Car" in text
    assert visual_description_from_task_options({"figure_note": "x"}, part=2) == ""


def test_prompt_loader_missing_version_raises():
    with pytest.raises(FileNotFoundError):
        PromptLoader().load("v999-missing")


def test_claude_provider_alias():
    assert ClaudeProvider is ClaudeWritingProvider


def test_evaluate_writing_essay_stores_request_metadata():
    async def run():
        with (
            patch(
                "app.writing.providers.factory.ClaudeWritingProvider.chat_json",
                new_callable=AsyncMock,
                return_value=(json.dumps(VALID_EVAL_JSON), {"content": []}),
            ),
            patch("app.writing.providers.claude_eval.claude_configured", return_value=True),
            patch("app.writing.providers.factory.get_settings") as settings,
            patch("app.writing.providers.claude_eval.get_settings") as claude_settings,
            patch("app.writing.providers.factory.check_claude_budget") as budget,
            patch("app.writing.providers.factory.is_claude_circuit_open") as circuit,
            patch("app.writing.providers.factory.consume_claude_eval"),
            patch("app.writing.providers.factory.record_eval_outcome"),
            patch("app.writing.providers.factory.record_claude_success"),
            patch("app.writing.providers.factory.log_writing_eval_request"),
        ):
            for s in (settings, claude_settings):
                s.return_value.writing_eval_stub = False
                s.return_value.ai_budget_fallback_stub = False
                s.return_value.writing_llm_primary = "claude"
                s.return_value.writing_llm_fallback = "none"
                s.return_value.anthropic_api_key = "sk-ant-test"
                s.return_value.anthropic_model = "claude-sonnet-4-6"
                s.return_value.writing_eval_timeout_sec = 90
            budget.return_value.ok = True
            budget.return_value.reason = None
            circuit.return_value.open = False
            return await evaluate_writing_essay(
                task_part=2,
                question="Discuss both views.",
                essay=VALID_ESSAY,
            )

    result = asyncio.run(run())
    assert result.provider_used == PROVIDER_NAME_ANTHROPIC_CLAUDE
    request = result.raw_store.get("request")
    assert isinstance(request, dict)
    assert request["prompt_version"] == "v5"
    assert request["model"] == result.model_name
    assert request["task_part"] == 2
    assert request["essay_word_count"] == 40
    assert request["max_tokens"] == 1500
    assert "requested_at" in request
    assert "estimated_input_tokens" in request
    assert "estimated_cost_usd" in request
    assert "latency_ms" in request
    assert request["attempt"] == 1
