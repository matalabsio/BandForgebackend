"""Unit tests for AI ops budget, circuit, estimator, and factory gates."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.ai_ops.budget import check_claude_budget, consume_claude_eval, get_budget_status
from app.ai_ops.circuit import (
    is_claude_circuit_open,
    record_claude_failure,
    reset_circuit_for_tests,
)
from app.ai_ops.estimator import estimate_tokens, estimate_writing_call
from app.ai_ops.metrics import reset_memory_metrics_for_tests, snapshot_today
from app.writing.providers.constants import PROVIDER_NAME_STUB
from app.writing.providers.factory import evaluate_writing_essay, writing_eval_configured

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


@pytest.fixture(autouse=True)
def _reset_ai_ops_state():
    reset_memory_metrics_for_tests()
    reset_circuit_for_tests()
    yield
    reset_memory_metrics_for_tests()
    reset_circuit_for_tests()


def test_estimate_tokens_roughly_chars_over_four():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 40) == 10


def test_estimate_writing_call_includes_cost():
    est = estimate_writing_call(
        system="system " * 50,
        user="user essay " * 80,
        essay_words=40,
    )
    assert est.input_tokens > 0
    assert est.output_tokens > 0
    assert est.estimated_cost_usd >= 0


def test_budget_blocks_when_daily_limit_reached():
    with patch("app.ai_ops.budget.get_settings") as settings, patch(
        "app.ai_ops.budget.ai_metrics.get_counter",
        side_effect=lambda metric, period="day": 20 if period == "day" else 20,
    ):
        settings.return_value.claude_daily_limit = 20
        settings.return_value.claude_monthly_limit = 100
        settings.return_value.claude_warning_at = 16
        status = check_claude_budget()
        assert status.ok is False
        assert "daily" in (status.reason or "")


def test_circuit_opens_after_threshold_failures():
    with patch("app.ai_ops.circuit.get_settings") as settings, patch(
        "app.ai_ops.circuit._get_redis",
        return_value=None,
    ):
        settings.return_value.ai_circuit_fail_threshold = 3
        settings.return_value.ai_circuit_cooldown_sec = 300
        assert is_claude_circuit_open().open is False
        record_claude_failure()
        record_claude_failure()
        status = record_claude_failure()
        assert status.open is True
        assert is_claude_circuit_open().open is True


def test_consume_claude_eval_increments_counter():
    with patch("app.ai_ops.budget.get_settings") as settings, patch(
        "app.ai_ops.metrics._get_redis",
        return_value=None,
    ):
        settings.return_value.claude_daily_limit = 100
        settings.return_value.claude_monthly_limit = 1000
        settings.return_value.claude_warning_at = 80
        before = get_budget_status().daily_used
        consume_claude_eval()
        assert get_budget_status().daily_used == before + 1


def test_factory_skips_claude_on_budget_and_uses_stub():
    async def run():
        with (
            patch("app.writing.providers.factory.get_settings") as settings,
            patch("app.writing.providers.factory.check_claude_budget") as budget,
            patch("app.writing.providers.factory.is_claude_circuit_open") as circuit,
            patch(
                "app.writing.providers.stub_eval.WRITING_STUB_DELAY_SEC",
                0,
            ),
            patch(
                "app.writing.providers.factory.ClaudeWritingProvider.chat_json",
                new_callable=AsyncMock,
            ) as claude_chat,
            patch("app.writing.providers.claude_eval.claude_configured", return_value=True),
            patch("app.writing.providers.groq_eval.groq_configured", return_value=False),
        ):
            settings.return_value.writing_eval_stub = False
            settings.return_value.writing_llm_primary = "claude"
            settings.return_value.writing_llm_fallback = "none"
            settings.return_value.ai_budget_fallback_stub = True
            settings.return_value.anthropic_model = "claude-sonnet-4-20250514"
            budget.return_value.ok = False
            budget.return_value.reason = "daily Claude limit reached"
            circuit.return_value.open = False
            return await evaluate_writing_essay(
                task_part=2,
                question="Discuss both views.",
                essay=VALID_ESSAY,
            )

    result = asyncio.run(run())
    assert result.provider_used == PROVIDER_NAME_STUB
    # Claude must not have been called
    # re-read: claude_chat is local to with block — assert via AsyncMock on class
    # We can't access claude_chat outside; re-run with assert inside:
    assert result.evaluation.overall_band == 6.0


def test_factory_budget_skip_never_calls_claude():
    called = {"claude": False}

    async def run():
        async def mark_claude(*_a, **_k):
            called["claude"] = True
            return json.dumps(VALID_EVAL_JSON), {}

        with (
            patch("app.writing.providers.factory.get_settings") as settings,
            patch("app.writing.providers.factory.check_claude_budget") as budget,
            patch("app.writing.providers.factory.is_claude_circuit_open") as circuit,
            patch(
                "app.writing.providers.stub_eval.WRITING_STUB_DELAY_SEC",
                0,
            ),
            patch(
                "app.writing.providers.factory.ClaudeWritingProvider.chat_json",
                new=AsyncMock(side_effect=mark_claude),
            ),
            patch("app.writing.providers.claude_eval.claude_configured", return_value=True),
            patch("app.writing.providers.groq_eval.groq_configured", return_value=False),
        ):
            settings.return_value.writing_eval_stub = False
            settings.return_value.writing_llm_primary = "claude"
            settings.return_value.writing_llm_fallback = "none"
            settings.return_value.ai_budget_fallback_stub = True
            settings.return_value.anthropic_model = "claude-test"
            budget.return_value.ok = False
            budget.return_value.reason = "daily limit"
            circuit.return_value.open = False
            return await evaluate_writing_essay(
                task_part=2,
                question="Discuss both views.",
                essay=VALID_ESSAY,
            )

    result = asyncio.run(run())
    assert called["claude"] is False
    assert result.provider_used == PROVIDER_NAME_STUB


def test_snapshot_today_shape():
    with patch("app.ai_ops.metrics._get_redis", return_value=None):
        snap = snapshot_today()
        assert "calls" in snap
        assert "estimated_cost_usd" in snap
        assert "success_rate_pct" in snap


def test_writing_eval_configured_respects_fallback_stub_flag():
    with (
        patch("app.writing.providers.claude_eval.claude_configured", return_value=False),
        patch("app.writing.providers.groq_eval.groq_configured", return_value=False),
        patch("app.writing.providers.factory.get_settings") as settings,
    ):
        settings.return_value.writing_eval_stub = False
        settings.return_value.ai_budget_fallback_stub = False
        settings.return_value.writing_llm_primary = "claude"
        settings.return_value.writing_llm_fallback = "groq"
        assert writing_eval_configured() is False

        settings.return_value.ai_budget_fallback_stub = True
        assert writing_eval_configured() is True
