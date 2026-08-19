from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.auth.utils import is_valid_india_phone, normalize_email, normalize_india_phone

IeltsPurpose = Literal["immigration", "university", "professional", "general"]
IeltsGoal = Literal[
    "australian_pr",
    "canada_pr",
    "uk_visa",
    "study_abroad",
    "professional_registration",
    "other",
]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SendOtpRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = normalize_india_phone(v)
        if not is_valid_india_phone(digits):
            raise ValueError("Enter a valid 10-digit Indian mobile number.")
        return digits


class VerifyOtpRequest(BaseModel):
    phone: str
    code: str = Field(min_length=4, max_length=4)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = normalize_india_phone(v)
        if not is_valid_india_phone(digits):
            raise ValueError("Invalid phone number.")
        return digits

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        from app.auth.constants import OTP_LENGTH

        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != OTP_LENGTH:
            raise ValueError(f"OTP must be {OTP_LENGTH} digits.")
        return digits


class SendEmailOtpRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        normalized = normalize_email(str(v))
        if not normalized:
            raise ValueError("Email is required.")
        return normalized


class VerifyEmailOtpRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        normalized = normalize_email(str(v))
        if not normalized:
            raise ValueError("Email is required.")
        return normalized

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        from app.auth.constants import EMAIL_OTP_LENGTH

        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != EMAIL_OTP_LENGTH:
            raise ValueError(f"OTP must be {EMAIL_OTP_LENGTH} digits.")
        return digits


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserPublic(BaseModel):
    id: UUID
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    email_verified: bool = False
    phone_verified: bool = False
    avatar_url: str | None = None
    avatar_display_url: str | None = None
    target_band: float | None = None
    ielts_purpose: IeltsPurpose | None = None
    ielts_goal: IeltsGoal | None = None
    role: str = "student"
    is_active: bool = True


class SessionUser(BaseModel):
    """Minimal authenticated user for shell rendering (layout, auth guards)."""

    id: UUID
    full_name: str | None = None
    email: str | None = None
    role: str = "student"
    avatar_display_url: str | None = None
    is_active: bool = True
    ielts_purpose: IeltsPurpose | None = None
    ielts_goal: IeltsGoal | None = None


class UpdateProfileRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str | None = None
    target_band: float | None = Field(default=None, ge=4.0, le=9.0)
    exam_date: str | None = Field(default=None, max_length=10)
    ielts_purpose: IeltsPurpose | None = None
    ielts_goal: IeltsGoal | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone_optional(cls, v: str | None) -> str | None:
        # Format / uniqueness are handled in the service as per-field warnings
        # so they never block full_name / target_band / exam_date.
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed or None

    @field_validator("target_band")
    @classmethod
    def round_target_band(cls, v: float | None) -> float | None:
        if v is None:
            return None
        return round(v * 2) / 2

    @field_validator("ielts_purpose", "ielts_goal", mode="before")
    @classmethod
    def empty_ielts_to_none(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, str):
            trimmed = v.strip().lower()
            return trimmed or None
        return v


class UpdateProfileResponse(BaseModel):
    user: UserPublic
    warnings: dict[str, str] = Field(default_factory=dict)


class AuthResponse(BaseModel):
    user: UserPublic
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    # Returned for client-side persistence (httpOnly cookies remain primary).
    refresh_token: str | None = None


class RestoreSessionRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=4096)


class MessageResponse(BaseModel):
    ok: bool = True
    message: str


class CollectLeadRequest(BaseModel):
    phone: str | None = None
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=120)
    channel: str = Field(default="start_modal", max_length=32)

    @field_validator("phone")
    @classmethod
    def validate_phone_optional(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        digits = normalize_india_phone(v)
        if not is_valid_india_phone(digits):
            raise ValueError("Enter a valid 10-digit Indian mobile number.")
        return digits


class GoogleAuthorizeResponse(BaseModel):
    authorization_url: str


class GoogleCallbackRequest(BaseModel):
    code: str = Field(min_length=1)
    state: str = Field(min_length=1)


class GoogleAuthResponse(BaseModel):
    redirect_to: str = "/dashboard"
    pending_verification: bool = False
    message: str | None = None
    user: UserPublic | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int = 0
