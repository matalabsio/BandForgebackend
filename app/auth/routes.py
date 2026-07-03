from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status

from app.auth.constants import (
    ACCESS_TOKEN_COOKIE,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    AUTH_ROUTER_PREFIX,
    REFRESH_TOKEN_COOKIE,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from app.auth.dependencies import (
    get_current_session_user,
    get_current_user,
    get_refresh_token,
)
from app.auth.google_oauth import (
    build_google_authorization_url,
    create_oauth_state,
    ensure_google_configured,
    exchange_code_for_userinfo,
    parse_oauth_state,
)
from app.auth.schemas import (
    AuthResponse,
    CollectLeadRequest,
    ForgotPasswordRequest,
    GoogleAuthResponse,
    GoogleAuthorizeResponse,
    GoogleCallbackRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    RestoreSessionRequest,
    SendOtpRequest,
    UpdateProfileRequest,
    SessionUser,
    UserPublic,
    VerifyEmailRequest,
    VerifyOtpRequest,
)
from app.auth import service
from app.config import get_settings

router = APIRouter(prefix=AUTH_ROUTER_PREFIX, tags=["auth"])


AUTH_TEMP_BLOCK_MSG = "Temporarily disabled. Continue with Google sign-in."


def _cookie_secure() -> bool:
    return get_settings().app_env == "production"


def _set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    secure = _cookie_secure()
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    secure = _cookie_secure()
    for key in (ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE):
        response.delete_cookie(key=key, path="/", secure=secure, samesite="lax")


@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest) -> MessageResponse:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=AUTH_TEMP_BLOCK_MSG,
    )


@router.post("/collect-lead", response_model=MessageResponse)
async def collect_lead(body: CollectLeadRequest) -> MessageResponse:
    return await service.collect_signup_lead(
        phone=body.phone,
        email=str(body.email) if body.email else None,
        full_name=body.full_name,
        channel=body.channel,
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, response: Response) -> AuthResponse:
    # Email/password is enabled for admin accounts only (admin panel sign-in).
    auth, new_refresh, _ = await service.login_user(
        email=str(body.email),
        password=body.password,
        admin_only=True,
    )
    _set_auth_cookies(
        response,
        access_token=auth.access_token,
        refresh_token=new_refresh,
    )
    return auth.model_copy(update={"refresh_token": new_refresh})


@router.post("/send-otp", response_model=MessageResponse)
async def send_otp(body: SendOtpRequest) -> MessageResponse:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Phone OTP is temporarily disabled.",
    )


@router.post("/verify-otp", response_model=AuthResponse)
async def verify_otp(body: VerifyOtpRequest, response: Response) -> AuthResponse:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Phone OTP is temporarily disabled.",
    )


@router.post("/verify-email", response_model=AuthResponse)
async def verify_email(body: VerifyEmailRequest, response: Response) -> AuthResponse:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=AUTH_TEMP_BLOCK_MSG,
    )


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    response: Response,
    refresh_token: Annotated[str | None, Depends(get_refresh_token)],
) -> AuthResponse:
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token.")
    auth, new_refresh, _ = await service.refresh_session(refresh_token=refresh_token)
    _set_auth_cookies(response, access_token=auth.access_token, refresh_token=new_refresh)
    return auth.model_copy(update={"refresh_token": new_refresh})


@router.post("/restore", response_model=AuthResponse)
async def restore_session(
    body: RestoreSessionRequest, response: Response
) -> AuthResponse:
    auth, new_refresh, _ = await service.refresh_session(
        refresh_token=body.refresh_token
    )
    _set_auth_cookies(response, access_token=auth.access_token, refresh_token=new_refresh)
    return auth.model_copy(update={"refresh_token": new_refresh})


@router.post("/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    refresh_token: Annotated[str | None, Depends(get_refresh_token)],
) -> MessageResponse:
    await service.logout_session(refresh_token=refresh_token)
    _clear_auth_cookies(response)
    return MessageResponse(message="Logged out.")


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(body: ForgotPasswordRequest) -> MessageResponse:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=AUTH_TEMP_BLOCK_MSG,
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(body: ResetPasswordRequest) -> MessageResponse:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=AUTH_TEMP_BLOCK_MSG,
    )


@router.get("/me", response_model=UserPublic)
async def me(user: Annotated[UserPublic, Depends(get_current_user)]) -> UserPublic:
    return user


@router.get("/session", response_model=SessionUser)
async def session(
    user: Annotated[SessionUser, Depends(get_current_session_user)],
) -> SessionUser:
    return user


@router.patch("/profile", response_model=UserPublic)
async def update_profile(
    body: UpdateProfileRequest,
    user: Annotated[UserPublic, Depends(get_current_user)],
) -> UserPublic:
    return await service.update_user_profile(user_id=user.id, body=body)


@router.post("/profile/avatar", response_model=UserPublic)
async def upload_profile_avatar(
    user: Annotated[UserPublic, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> UserPublic:
    raw = await file.read()
    content_type = file.content_type or "image/jpeg"
    return await service.upload_user_avatar(
        user_id=user.id,
        content=raw,
        content_type=content_type,
    )


@router.get("/google/authorize", response_model=GoogleAuthorizeResponse)
async def google_authorize(next: str = "/dashboard") -> GoogleAuthorizeResponse:
    ensure_google_configured()
    state = create_oauth_state(next_path=next)
    return GoogleAuthorizeResponse(
        authorization_url=build_google_authorization_url(state=state),
    )


@router.post("/google/callback", response_model=GoogleAuthResponse)
async def google_callback(
    body: GoogleCallbackRequest, response: Response
) -> GoogleAuthResponse:
    ensure_google_configured()
    redirect_to = parse_oauth_state(body.state)
    profile = await exchange_code_for_userinfo(code=body.code)
    google_id = profile.get("sub")
    email = profile.get("email")
    if not google_id or not email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Google account must share email.",
        )
    if profile.get("email_verified") is False:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Google email is not verified.",
        )
    result = await service.google_login_or_register(
        google_id=str(google_id),
        email=str(email),
        full_name=profile.get("name"),
    )
    if result.pending_redirect_to:
        return GoogleAuthResponse(
            redirect_to=result.pending_redirect_to,
            pending_verification=True,
            message=result.message,
        )
    assert result.auth is not None and result.refresh_token is not None
    _set_auth_cookies(
        response,
        access_token=result.auth.access_token,
        refresh_token=result.refresh_token,
    )
    return GoogleAuthResponse(
        user=result.auth.user,
        access_token=result.auth.access_token,
        refresh_token=result.refresh_token,
        token_type=result.auth.token_type,
        expires_in=result.auth.expires_in,
        redirect_to=redirect_to,
    )
