"""Rate limiting for diagnostic evaluate-writing (3 per IP per hour via Redis)."""

from __future__ import annotations

from fastapi import Request

from app.security.rate_limit import enforce_evaluate_writing_rate_limit


def check_evaluate_writing_rate_limit(request: Request) -> None:
    """Raise 429 if IP exceeded 3 evaluations in the last hour."""
    enforce_evaluate_writing_rate_limit(request)


def record_evaluate_writing_rate_limit(request: Request) -> None:
    """Count a live AI evaluation against the IP limit (not used on cache hits)."""
    check_evaluate_writing_rate_limit(request)
