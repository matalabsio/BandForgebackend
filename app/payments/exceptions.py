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


class GuestCheckoutNotAllowedError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            detail="Guest accounts cannot purchase. Please sign up or sign in.",
        )


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


class WebhookEventIdRequiredError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail="Webhook event id is required.",
        )


class WebhookTransientError(HTTPException):
    """503 — ask Razorpay to retry; fulfillment may succeed on a later delivery."""

    def __init__(self, detail: str = "Webhook fulfillment temporarily unavailable.") -> None:
        super().__init__(status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


class PaymentAmountMismatchError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail="Payment amount does not match the order.",
        )


class PaymentNotCapturedError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail="Payment has not been captured yet.",
        )


class PaymentRefundedError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail="This payment was refunded and cannot be fulfilled.",
        )


class PaymentFetchError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify payment with Razorpay. Please try again.",
        )


class PaymentConsistencyError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment record could not be confirmed. Please try again.",
        )


class RazorpayAuthError(HTTPException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail
            or (
                "Razorpay API authentication failed. Regenerate Test mode API keys in "
                "Razorpay Dashboard → Settings → API Keys, update backend/.env "
                "(RAZORPAY_KEY_ID + RAZORPAY_KEY_SECRET must be a matching pair), "
                "then restart the backend."
            ),
        )


class CouponInvalidError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail="Invalid coupon code.",
        )


class CouponInactiveError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail="This coupon is no longer active.",
        )


class CouponExpiredError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail="This coupon has expired.",
        )


class CouponExhaustedError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail="This coupon has already been used.",
        )


class CouponUserAlreadyRedeemedError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            detail="You have already redeemed a coupon.",
        )
