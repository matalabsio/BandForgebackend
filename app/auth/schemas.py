from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.auth.utils import is_valid_india_phone, normalize_india_phone


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
    code: str = Field(min_length=6, max_length=6)

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
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != 6:
            raise ValueError("OTP must be 6 digits.")
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


class AuthResponse(BaseModel):
    user: UserPublic
    access_token: str
    token_type: str = "bearer"
    expires_in: int


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
    token_type: str = "bearer"
    expires_in: int = 0
