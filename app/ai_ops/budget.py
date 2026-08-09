"""Claude / Groq eval-count daily/monthly budget checks."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.ai_ops import metrics as ai_metrics
from app.config import get_settings

logger = logging.getLogger(__name__)

CLAUDE_EVALS_METRIC = "claude_evals"
GROQ_EVALS_METRIC = "groq_evals"


@dataclass(frozen=True)
class BudgetStatus:
    ok: bool
    daily_used: int
    daily_limit: int
    monthly_used: int
    monthly_limit: int
    warning: bool
    reason: str | None = None


def _warning_threshold(daily_limit: int, *, warning_at: int) -> int:
    if warning_at > 0:
        return int(warning_at)
    return max(1, int(daily_limit * 0.8))


def _status_for_metric(
    metric: str,
    *,
    daily_limit: int,
    monthly_limit: int,
    warning_at: int,
    label: str,
) -> BudgetStatus:
    daily_limit = max(0, int(daily_limit))
    monthly_limit = max(0, int(monthly_limit))
    daily_used, monthly_used = ai_metrics.get_day_month_counters(metric)

    if daily_limit > 0 and daily_used >= daily_limit:
        return BudgetStatus(
            ok=False,
            daily_used=daily_used,
            daily_limit=daily_limit,
            monthly_used=monthly_used,
            monthly_limit=monthly_limit,
            warning=True,
            reason=f"daily {label} limit reached ({daily_used}/{daily_limit})",
        )
    if monthly_limit > 0 and monthly_used >= monthly_limit:
        return BudgetStatus(
            ok=False,
            daily_used=daily_used,
            daily_limit=daily_limit,
            monthly_used=monthly_used,
            monthly_limit=monthly_limit,
            warning=True,
            reason=f"monthly {label} limit reached ({monthly_used}/{monthly_limit})",
        )

    warn_at = (
        _warning_threshold(daily_limit, warning_at=warning_at) if daily_limit > 0 else 0
    )
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


def get_budget_status() -> BudgetStatus:
    settings = get_settings()
    return _status_for_metric(
        CLAUDE_EVALS_METRIC,
        daily_limit=settings.claude_daily_limit,
        monthly_limit=settings.claude_monthly_limit,
        warning_at=settings.claude_warning_at,
        label="Claude",
    )


def get_groq_budget_status() -> BudgetStatus:
    settings = get_settings()
    return _status_for_metric(
        GROQ_EVALS_METRIC,
        daily_limit=settings.groq_daily_limit,
        monthly_limit=settings.groq_monthly_limit,
        warning_at=settings.groq_warning_at,
        label="Groq",
    )


def check_claude_budget() -> BudgetStatus:
    status = get_budget_status()
    settings = get_settings()
    if status.warning and status.ok:
        logger.warning(
            "Claude budget warning: daily %s/%s (threshold %s)",
            status.daily_used,
            status.daily_limit,
            _warning_threshold(
                status.daily_limit, warning_at=settings.claude_warning_at
            ),
        )
    if not status.ok:
        logger.warning("Claude budget blocked: %s", status.reason)
    return status


def check_groq_budget() -> BudgetStatus:
    status = get_groq_budget_status()
    settings = get_settings()
    if status.warning and status.ok:
        logger.warning(
            "Groq budget warning: daily %s/%s (threshold %s)",
            status.daily_used,
            status.daily_limit,
            _warning_threshold(status.daily_limit, warning_at=settings.groq_warning_at),
        )
    if not status.ok:
        logger.warning("Groq budget blocked: %s", status.reason)
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


def consume_groq_eval() -> None:
    """Increment Groq eval counters after a live Groq attempt starts."""
    ai_metrics.incr(GROQ_EVALS_METRIC)
    status = get_groq_budget_status()
    if status.warning and status.ok:
        logger.warning(
            "Groq budget warning after consume: daily %s/%s",
            status.daily_used,
            status.daily_limit,
        )


__all__ = [
    "BudgetStatus",
    "CLAUDE_EVALS_METRIC",
    "GROQ_EVALS_METRIC",
    "check_claude_budget",
    "check_groq_budget",
    "consume_claude_eval",
    "consume_groq_eval",
    "get_budget_status",
    "get_groq_budget_status",
]
