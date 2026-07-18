"""AI infrastructure & operations — budget, metrics, circuit breaker."""

from __future__ import annotations

from app.ai_ops.budget import (
    BudgetStatus,
    check_claude_budget,
    consume_claude_eval,
    get_budget_status,
)
from app.ai_ops.circuit import (
    CircuitStatus,
    is_claude_circuit_open,
    record_claude_failure,
    record_claude_success,
)
from app.ai_ops.estimator import (
    WritingCallEstimate,
    estimate_tokens,
    estimate_writing_call,
)
from app.ai_ops.logging import log_writing_eval_request
from app.ai_ops.metrics import (
    recent_failures,
    record_eval_outcome,
    snapshot_today,
)

__all__ = [
    "BudgetStatus",
    "CircuitStatus",
    "WritingCallEstimate",
    "check_claude_budget",
    "consume_claude_eval",
    "estimate_tokens",
    "estimate_writing_call",
    "get_budget_status",
    "is_claude_circuit_open",
    "log_writing_eval_request",
    "recent_failures",
    "record_claude_failure",
    "record_claude_success",
    "record_eval_outcome",
    "snapshot_today",
]
