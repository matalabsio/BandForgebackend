"""Claude eval-count daily/monthly budget checks."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.ai_ops import metrics as ai_metrics
from app.config import get_settings

logger = logging.getLogger(__name__)

CLAUDE_EVALS_METRIC = "claude_evals"


@dataclass(frozen=True)
class BudgetStatus:
    ok: bool
    daily_used: int
    daily_limit: int
    monthly_used: int
    monthly_limit: int
    warning: bool
    reason: str | None = None


def _warning_threshold(daily_limit: int) -> int:
    settings = get_settings()
    if settings.claude_warning_at > 0:
        return int(settings.claude_warning_at)
    return max(1, int(daily_limit * 0.8))


def get_budget_status() -> BudgetStatus:
    settings = get_settings()
    daily_limit = max(0, int(settings.claude_daily_limit))
    monthly_limit = max(0, int(settings.claude_monthly_limit))
    daily_used = ai_metrics.get_counter(CLAUDE_EVALS_METRIC, period="day")
    monthly_used = ai_metrics.get_counter(CLAUDE_EVALS_METRIC, period="month")

    if daily_limit > 0 and daily_used >= daily_limit:
        return BudgetStatus(
            ok=False,
            daily_used=daily_used,
            daily_limit=daily_limit,
            monthly_used=monthly_used,
            monthly_limit=monthly_limit,
            warning=True,
            reason=f"daily Claude limit reached ({daily_used}/{daily_limit})",
        )
    if monthly_limit > 0 and monthly_used >= monthly_limit:
        return BudgetStatus(
            ok=False,
            daily_used=daily_used,
            daily_limit=daily_limit,
            monthly_used=monthly_used,
            monthly_limit=monthly_limit,
            warning=True,
            reason=f"monthly Claude limit reached ({monthly_used}/{monthly_limit})",
        )

    warn_at = _warning_threshold(daily_limit) if daily_limit > 0 else 0
    warning = daily_limit > 0 and daily_used >= warn_at
    return BudgetStatus(
        ok=True,
        daily_used=daily_used,
        daily_limit=daily_limit,
        monthly_used=monthly_used,
        monthly_limit=monthly_limit,
        warning=warning,
        reason=None,
    )


def check_claude_budget() -> BudgetStatus:
    status = get_budget_status()
    if status.warning and status.ok:
        logger.warning(
            "Claude budget warning: daily %s/%s (threshold %s)",
            status.daily_used,
            status.daily_limit,
            _warning_threshold(status.daily_limit),
        )
    if not status.ok:
        logger.warning("Claude budget blocked: %s", status.reason)
    return status


def consume_claude_eval() -> None:
    """Increment Claude eval counters after a live Claude attempt starts."""
    ai_metrics.incr(CLAUDE_EVALS_METRIC)
    status = get_budget_status()
    if status.warning and status.ok:
        logger.warning(
            "Claude budget warning after consume: daily %s/%s",
            status.daily_used,
            status.daily_limit,
        )


__all__ = [
    "BudgetStatus",
    "CLAUDE_EVALS_METRIC",
    "check_claude_budget",
    "consume_claude_eval",
    "get_budget_status",
]
