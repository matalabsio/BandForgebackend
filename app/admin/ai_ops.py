"""Admin AI ops — metrics snapshot and health."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.admin.parallel import run_parallel
from app.ai_ops.budget import get_budget_status
from app.ai_ops.circuit import is_claude_circuit_open
from app.ai_ops.metrics import recent_failures, snapshot_today
from app.cache.hybrid_cache import get_json, redis_status, set_json
from app.config import get_settings
from app.db.supabase_client import get_supabase
from app.perf.timing import timed_call, timed_supabase
from app.speaking.claude_client import claude_configured
from app.writing.providers.groq_eval import GroqWritingProvider

_AI_METRICS_CACHE_KEY = "bf:admin:ai_metrics:v1"
_AI_METRICS_CACHE_TTL_SEC = 10


class AiBudgetSnapshot(BaseModel):
    ok: bool
    daily_used: int
    daily_limit: int
    monthly_used: int
    monthly_limit: int
    warning: bool
    reason: str | None = None


class AiCircuitSnapshot(BaseModel):
    open: bool
    failures: int
    open_until: float | None = None
    reason: str | None = None


class AiFailureItem(BaseModel):
    provider: str
    reason: str
    at: str


class AiMetricsResponse(BaseModel):
    period: str
    day: str
    calls: int
    success: int
    errors: int
    retries: int
    stub_calls: int
    cache_hits: int
    cache_misses: int
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: float
    avg_latency_ms: float
    success_rate_pct: float
    retry_rate_pct: float
    redis_status: str
    generated_at: str
    budget: AiBudgetSnapshot
    circuit: AiCircuitSnapshot
    recent_failures: list[AiFailureItem] = Field(default_factory=list)
    speaking_pending: int = 0
    speaking_failed: int = 0


class AiHealthResponse(BaseModel):
    redis_status: str
    claude_configured: bool
    groq_configured: bool
    writing_eval_stub: bool
    budget_ok: bool
    circuit_open: bool
    speaking_pending: int = 0
    speaking_failed: int = 0


def _speaking_ai_job_counts() -> tuple[int, int]:
    """Count speaking reviews that look pending / failed for AI eval."""
    pending = 0
    failed = 0
    try:
        result = timed_supabase(
            "ai.speaking_reviews.ai_scores",
            lambda: (
                get_supabase()
                .table("speaking_reviews")
                .select("ai_scores")
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            ),
        )
        rows = result.data or []
        for row in rows:
            scores = row.get("ai_scores") if isinstance(row, dict) else None
            if not isinstance(scores, dict):
                pending += 1
                continue
            status = str(scores.get("status") or "").lower()
            if status in ("", "pending"):
                pending += 1
            elif status in ("ai_failed", "failed", "error"):
                failed += 1
    except Exception:
        return 0, 0
    return pending, failed


def _assemble_ai_metrics() -> AiMetricsResponse:
    parts = timed_call(
        "ai.metrics.parallel",
        lambda: run_parallel(
            {
                "snap": snapshot_today,
                "budget": get_budget_status,
                "circuit": is_claude_circuit_open,
                "speaking": _speaking_ai_job_counts,
                "failures": lambda: recent_failures(10),
            }
        ),
    )
    snap = parts["snap"]
    budget = parts["budget"]
    circuit = parts["circuit"]
    pending, failed = parts["speaking"]
    failures = [
        AiFailureItem(
            provider=str(item.get("provider") or "unknown"),
            reason=str(item.get("reason") or ""),
            at=str(item.get("at") or ""),
        )
        for item in parts["failures"]
    ]
    return AiMetricsResponse(
        **snap,
        budget=AiBudgetSnapshot(
            ok=budget.ok,
            daily_used=budget.daily_used,
            daily_limit=budget.daily_limit,
            monthly_used=budget.monthly_used,
            monthly_limit=budget.monthly_limit,
            warning=budget.warning,
            reason=budget.reason,
        ),
        circuit=AiCircuitSnapshot(
            open=circuit.open,
            failures=circuit.failures,
            open_until=circuit.open_until,
            reason=circuit.reason,
        ),
        recent_failures=failures,
        speaking_pending=pending,
        speaking_failed=failed,
    )


def get_ai_metrics() -> AiMetricsResponse:
    cached = timed_call(
        "ai.metrics.cache_get",
        lambda: get_json(_AI_METRICS_CACHE_KEY),
    )
    if isinstance(cached, dict):
        try:
            return AiMetricsResponse.model_validate(cached)
        except Exception:
            pass

    response = _assemble_ai_metrics()
    timed_call(
        "ai.metrics.cache_set",
        lambda: set_json(
            _AI_METRICS_CACHE_KEY,
            response.model_dump(mode="json"),
            _AI_METRICS_CACHE_TTL_SEC,
        ),
    )
    return response


def get_ai_health() -> AiHealthResponse:
    settings = get_settings()
    parts = timed_call(
        "ai.health.parallel",
        lambda: run_parallel(
            {
                "budget": get_budget_status,
                "circuit": is_claude_circuit_open,
                "speaking": _speaking_ai_job_counts,
                "redis": redis_status,
            }
        ),
    )
    budget = parts["budget"]
    circuit = parts["circuit"]
    pending, failed = parts["speaking"]
    return AiHealthResponse(
        redis_status=parts["redis"],
        claude_configured=claude_configured(),
        groq_configured=GroqWritingProvider().configured(),
        writing_eval_stub=bool(settings.writing_eval_stub),
        budget_ok=budget.ok,
        circuit_open=circuit.open,
        speaking_pending=pending,
        speaking_failed=failed,
    )


__all__ = [
    "AiHealthResponse",
    "AiMetricsResponse",
    "get_ai_health",
    "get_ai_metrics",
]
