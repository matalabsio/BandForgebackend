"""Typed HTTP errors for the payments module."""

from __future__ import annotations

from fastapi import HTTPException, status


class PaymentsDisabledError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payments are not enabled.",
        )


class PlanNotFoundError(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, detail="Plan not found.")


class PaymentNotFoundError(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, detail="Payment not found.")


class SignatureVerificationError(HTTPException):
    def __init__(self, detail: str = "Payment signature verification failed.") -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, detail=detail)


class WebhookVerificationError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail="Webhook signature verification failed.",
        )
