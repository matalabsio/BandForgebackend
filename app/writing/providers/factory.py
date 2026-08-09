"""Factory for writing evaluation — stub / Claude / Groq with AI ops gates."""

from __future__ import annotations

import logging

from app.ai_ops.budget import (
    check_claude_budget,
    check_groq_budget,
    consume_claude_eval,
    consume_groq_eval,
)
from app.ai_ops.circuit import (
    is_claude_circuit_open,
    record_claude_failure,
    record_claude_success,
)
from app.ai_ops.estimator import estimate_writing_call
from app.ai_ops.logging import log_writing_eval_request
from app.ai_ops.metrics import record_eval_outcome, record_failure
from app.config import get_settings
from app.diagnostic.writing_prompt import build_user_prompt, get_system_prompt
from app.writing.evaluation import word_count
from app.writing.providers.claude_eval import ClaudeWritingProvider
from app.writing.providers.constants import (
    PROVIDER_NAME_ANTHROPIC_CLAUDE,
    PROVIDER_NAME_GROQ,
    PROVIDER_NAME_STUB,
    WritingLLMProviderKind,
)
from app.writing.providers.evaluation_call import (
    WritingEvaluationResult,
    call_writing_evaluation_with_retry,
)
from app.writing.providers.groq_eval import GroqWritingProvider
from app.writing.providers.stub_eval import StubWritingProvider

logger = logging.getLogger(__name__)

_SUPPORTED = ", ".join(k.value for k in WritingLLMProviderKind if k != WritingLLMProviderKind.NONE)


def _parse_kind(raw: str) -> WritingLLMProviderKind:
    normalized = (raw or WritingLLMProviderKind.CLAUDE.value).strip().lower()
    try:
        return WritingLLMProviderKind(normalized)
    except ValueError:
        raise ValueError(
            f'Unknown writing LLM provider: "{raw}". Supported: {_SUPPORTED}, none.'
        ) from None


def _provider_for_kind(kind: WritingLLMProviderKind):
    match kind:
        case WritingLLMProviderKind.CLAUDE:
            return ClaudeWritingProvider()
        case WritingLLMProviderKind.GROQ:
            return GroqWritingProvider()
        case WritingLLMProviderKind.NONE:
            return None
    raise ValueError(f'Unknown writing LLM provider: "{kind}".')


def writing_eval_configured() -> bool:
    settings = get_settings()
    if settings.writing_eval_stub:
        return True
    if settings.ai_budget_fallback_stub:
        return True
    primary = _parse_kind(settings.writing_llm_primary)
    fallback = _parse_kind(settings.writing_llm_fallback)
    for kind in (primary, fallback):
        provider = _provider_for_kind(kind)
        if provider is not None and provider.configured():
            return True
    return False


def _precall_estimate(
    *,
    task_part: int,
    question: str,
    essay: str,
    visual_description: str | None = None,
    target_band: float | None = None,
):
    words = word_count(essay)
    user = build_user_prompt(
        task_part=task_part,
        question=question,
        essay=essay,
        visual_description=visual_description,
        word_count=words,
        target_band=target_band,
    )
    return estimate_writing_call(
        system=get_system_prompt(),
        user=user,
        essay_words=words,
    )


async def _run_provider(
    *,
    provider,
    task_part: int,
    question: str,
    essay: str,
    visual_description: str | None = None,
    target_band: float | None = None,
) -> WritingEvaluationResult:
    async def llm_call(system: str, user: str) -> tuple[str, dict]:
        return await provider.chat_json(system=system, user=user)

    return await call_writing_evaluation_with_retry(
        llm_call=llm_call,
        task_part=task_part,
        question=question,
        essay=essay,
        provider_label=provider.name,
        model_name=provider.model,
        provider_used=provider.name,
        visual_description=visual_description,
        target_band=target_band,
    )


def _record_success(result: WritingEvaluationResult, *, is_stub: bool) -> None:
    est = result.estimate
    record_eval_outcome(
        provider=result.provider_used,
        success=True,
        latency_ms=result.latency_ms,
        retries=result.retry_count,
        tokens_in=est.input_tokens if est else 0,
        tokens_out=est.output_tokens if est else 0,
        cost_usd=est.estimated_cost_usd if est and not is_stub else 0.0,
        is_stub=is_stub,
    )
    if result.provider_used == PROVIDER_NAME_ANTHROPIC_CLAUDE:
        record_claude_success()


def _record_provider_failure(provider_name: str, exc: Exception) -> None:
    record_failure(provider_name, str(exc))
    record_eval_outcome(
        provider=provider_name,
        success=False,
        latency_ms=0,
        retries=0,
    )
    if provider_name == PROVIDER_NAME_ANTHROPIC_CLAUDE:
        record_claude_failure()


async def evaluate_writing_essay(
    *,
    task_part: int,
    question: str,
    essay: str,
    visual_description: str | None = None,
    target_band: float | None = None,
) -> WritingEvaluationResult:
    """Evaluate an essay using stub (if enabled), else primary LLM with fallback."""
    settings = get_settings()
    estimate = _precall_estimate(
        task_part=task_part,
        question=question,
        essay=essay,
        visual_description=visual_description,
        target_band=target_band,
    )

    if settings.writing_eval_stub:
        provider = StubWritingProvider(task_part=task_part, essay=essay)
        log_writing_eval_request(
            provider=provider.name,
            model=provider.model,
            estimate=estimate,
        )
        logger.info("Calling writing evaluator: stub (offline)")
        result = await _run_provider(
            provider=provider,
            task_part=task_part,
            question=question,
            essay=essay,
            visual_description=visual_description,
            target_band=target_band,
        )
        _record_success(result, is_stub=True)
        return result

    primary_kind = _parse_kind(settings.writing_llm_primary)
    fallback_kind = _parse_kind(settings.writing_llm_fallback)

    chain: list[WritingLLMProviderKind] = []
    if primary_kind != WritingLLMProviderKind.NONE:
        chain.append(primary_kind)
    if fallback_kind != WritingLLMProviderKind.NONE and fallback_kind not in chain:
        chain.append(fallback_kind)

    budget = check_claude_budget()
    groq_budget = check_groq_budget()
    circuit = is_claude_circuit_open()
    skip_claude_reason: str | None = None
    skip_groq_reason: str | None = None
    if not budget.ok:
        skip_claude_reason = budget.reason or "budget_exceeded"
    elif circuit.open:
        skip_claude_reason = circuit.reason or "circuit_open"
    if not groq_budget.ok:
        skip_groq_reason = groq_budget.reason or "budget_exceeded"

    last_error: Exception | None = None
    for kind in chain:
        if kind == WritingLLMProviderKind.CLAUDE and skip_claude_reason:
            log_writing_eval_request(
                provider=PROVIDER_NAME_ANTHROPIC_CLAUDE,
                model=settings.anthropic_model,
                estimate=estimate,
                skipped_reason=skip_claude_reason,
            )
            logger.warning("Skipping Claude: %s", skip_claude_reason)
            continue
        if kind == WritingLLMProviderKind.GROQ and skip_groq_reason:
            log_writing_eval_request(
                provider=PROVIDER_NAME_GROQ,
                model=settings.groq_model,
                estimate=estimate,
                skipped_reason=skip_groq_reason,
            )
            logger.warning("Skipping Groq: %s", skip_groq_reason)
            continue

        provider = _provider_for_kind(kind)
        if provider is None or not provider.configured():
            logger.info("Writing provider %s not configured — skipping", kind.value)
            continue

        log_writing_eval_request(
            provider=provider.name,
            model=provider.model,
            estimate=estimate,
        )
        try:
            logger.info("Calling writing evaluator: %s (%s)", provider.name, provider.model)
            if kind == WritingLLMProviderKind.CLAUDE:
                consume_claude_eval()
            elif kind == WritingLLMProviderKind.GROQ:
                consume_groq_eval()
            result = await _run_provider(
                provider=provider,
                task_part=task_part,
                question=question,
                essay=essay,
                visual_description=visual_description,
                target_band=target_band,
            )
            _record_success(result, is_stub=False)
            return result
        except Exception as exc:
            last_error = exc
            _record_provider_failure(provider.name, exc)
            logger.warning(
                "Writing evaluation failed with %s — trying fallback",
                provider.name,
                exc_info=exc,
            )

    if settings.ai_budget_fallback_stub:
        provider = StubWritingProvider(task_part=task_part, essay=essay)
        reason = skip_claude_reason or (str(last_error) if last_error else "no_provider")
        log_writing_eval_request(
            provider=PROVIDER_NAME_STUB,
            model=PROVIDER_NAME_STUB,
            estimate=estimate,
            skipped_reason=f"fallback_stub:{reason}",
        )
        logger.warning("Falling back to stub evaluator (%s)", reason)
        result = await _run_provider(
            provider=provider,
            task_part=task_part,
            question=question,
            essay=essay,
            visual_description=visual_description,
            target_band=target_band,
        )
        _record_success(result, is_stub=True)
        return result

    raise RuntimeError(
        str(last_error) if last_error else "No writing evaluation provider is configured"
    )
