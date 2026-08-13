import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from app.auth.constants import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    EMAIL_VERIFY_EXPIRE_HOURS,
    OTP_PURPOSE_LOGIN,
    PASSWORD_RESET_EXPIRE_HOURS,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from app.auth.email import send_password_reset_email, send_verification_email
from app.auth.jwt import create_access_token, create_refresh_token, decode_refresh_token
from app.auth.otp import OtpError, create_and_send_otp, verify_otp_code
from app.auth.schemas import (
    AuthResponse,
    MessageResponse,
    SessionUser,
    UpdateProfileRequest,
    UpdateProfileResponse,
    UserPublic,
)
from app.storage.r2 import delete_object, upload_object
from app.auth.security import hash_password, verify_password
from app.auth.utils import (
    generate_opaque_token,
    hash_token,
    is_valid_india_phone,
    normalize_india_phone,
    phone_e164,
    utcnow,
)
from app.config import get_settings
from app.db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

PHONE_OTP_DISABLED_MSG = "Phone OTP is not enabled yet."


def _ensure_phone_otp_enabled() -> None:
    if not get_settings().phone_otp_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, PHONE_OTP_DISABLED_MSG)


def _email_verification_required() -> bool:
    """Temporary: email verification disabled until Resend/production is configured."""
    return False


async def _queue_email_verification(
    *, user_id: UUID, email: str, full_name: str | None
) -> None:
    """Create a verification token and send (or log) the Resend email."""
    sb = get_supabase()
    settings = get_settings()
    verify_token = generate_opaque_token()
    now = utcnow()
    sb.table("password_reset_tokens").insert(
        {
            "user_id": str(user_id),
            "token_hash": hash_token(verify_token),
            "expires_at": (now + timedelta(hours=EMAIL_VERIFY_EXPIRE_HOURS)).isoformat(),
        }
    ).execute()

    from app.auth.email import _verify_link

    verify_url = _verify_link(verify_token)
    sent = await send_verification_email(
        to=email.lower(), token=verify_token, name=full_name
    )
    if not sent and settings.app_env != "production":
        logger.info("Dev verification link for %s: %s", email.lower(), verify_url)


@dataclass
class GoogleLoginResult:
    auth: AuthResponse | None = None
    refresh_token: str | None = None
    session_id: str | None = None
    pending_redirect_to: str | None = None
    message: str | None = None


def _avatar_display_url(key: str | None) -> str | None:
    if not key:
        return None
    try:
        from app.storage.r2 import generate_signed_url

        return generate_signed_url(key, expiry=86400)
    except Exception:
        logger.warning("avatar presign failed for key=%s", key, exc_info=True)
        return None


def _row_to_user(row: dict[str, Any]) -> UserPublic:
    target = row.get("target_band")
    return UserPublic(
        id=UUID(str(row["id"])),
        email=row.get("email"),
        full_name=row.get("full_name"),
        phone=row.get("phone"),
        email_verified=row.get("email_verified_at") is not None,
        phone_verified=row.get("phone_verified_at") is not None,
        avatar_url=row.get("avatar_url"),
        avatar_display_url=_avatar_display_url(row.get("avatar_url")),
        target_band=float(target) if target is not None else None,
        ielts_purpose=row.get("ielts_purpose"),
        ielts_goal=row.get("ielts_goal"),
        role=str(row.get("role") or "student"),
        is_active=bool(row.get("is_active", True)),
    )


def _row_to_session(row: dict[str, Any]) -> SessionUser:
    return SessionUser(
        id=UUID(str(row["id"])),
        full_name=row.get("full_name"),
        email=row.get("email"),
        role=str(row.get("role") or "student"),
        avatar_display_url=_avatar_display_url(row.get("avatar_url")),
        is_active=bool(row.get("is_active", True)),
        ielts_purpose=row.get("ielts_purpose"),
        ielts_goal=row.get("ielts_goal"),
    )


def _assert_user_accessible(
    *,
    email: str | None,
    email_verified_at: Any,
    is_active: bool,
) -> None:
    if not is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Account is deactivated.",
        )
    if (
        _email_verification_required()
        and email
        and email_verified_at is None
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Verify your email before continuing.",
        )


def _auth_response(user: UserPublic, access_token: str) -> AuthResponse:
    return AuthResponse(
        user=user,
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def build_auth_response(user: UserPublic, access_token: str) -> AuthResponse:
    return _auth_response(user, access_token)


async def issue_session_tokens(
    *,
    user_id: UUID,
    email: str | None,
    phone: str | None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, str, str]:
    return await _issue_tokens(
        user_id=user_id,
        email=email,
        phone=phone,
        user_agent=user_agent,
        ip_address=ip_address,
    )


async def collect_signup_lead(
    *,
    phone: str | None,
    email: str | None,
    full_name: str | None,
    channel: str,
) -> MessageResponse:
    if not phone and not email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Phone or email is required.",
        )

    sb = get_supabase()
    now = utcnow().isoformat()
    e164 = phone_e164(phone) if phone else None
    email_lower = email.lower() if email else None

    row: dict[str, Any] = {
        "full_name": full_name,
        "channel": channel,
        "updated_at": now,
    }
    if e164:
        row["phone"] = e164
    if email_lower:
        row["email"] = email_lower

    existing = None
    if e164:
        existing = (
            sb.table("signup_leads").select("id").eq("phone", e164).limit(1).execute()
        )
    if not (existing and existing.data) and email_lower:
        existing = (
            sb.table("signup_leads")
            .select("id")
            .eq("email", email_lower)
            .limit(1)
            .execute()
        )

    try:
        if existing and existing.data:
            sb.table("signup_leads").update(row).eq("id", existing.data[0]["id"]).execute()
        else:
            row["created_at"] = now
            sb.table("signup_leads").insert(row).execute()
    except Exception as exc:
        logger.exception("signup_leads write failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Could not save your details. Try again.",
        ) from exc

    return MessageResponse(
        message="Thanks — we saved your number. SMS sign-in will be enabled soon.",
    )


async def register_user(
    *, email: str, password: str, full_name: str | None
) -> MessageResponse:
    sb = get_supabase()
    existing = (
        sb.table("users").select("id").eq("email", email.lower()).limit(1).execute()
    )
    if existing.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered.")

    now = utcnow()
    settings = get_settings()
    row: dict[str, Any] = {
        "email": email.lower(),
        "full_name": full_name,
        "password_hash": hash_password(password),
        "updated_at": now.isoformat(),
    }
    if settings.auth_skip_email_verify:
        row["email_verified_at"] = now.isoformat()

    inserted = sb.table("users").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create user.")
    user_row = inserted.data[0]
    user_id = UUID(str(user_row["id"]))

    if _email_verification_required():
        await _queue_email_verification(
            user_id=user_id, email=email.lower(), full_name=full_name
        )
        await collect_signup_lead(
            phone=None,
            email=email.lower(),
            full_name=full_name,
            channel="email",
        )
        return MessageResponse(
            message="Check your email for a verification link to continue.",
        )

    await collect_signup_lead(
        phone=None,
        email=email.lower(),
        full_name=full_name,
        channel="email",
    )
    return MessageResponse(
        message="Account created. You can sign in now.",
    )


ADMIN_ROLES = frozenset({"admin", "super_admin"})


async def login_user(
    *,
    email: str,
    password: str,
    admin_only: bool = False,
) -> tuple[AuthResponse, str, str]:
    sb = get_supabase()
    result = (
        sb.table("users")
        .select("*")
        .eq("email", email.lower())
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    row = result.data[0]
    if not verify_password(password, row.get("password_hash")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")

    role = str(row.get("role") or "student")
    if admin_only and role not in ADMIN_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Temporarily disabled. Continue with Google sign-in.",
        )

    if admin_only:
        from app.admin.dependencies import is_admin_email_allowed

        if not is_admin_email_allowed(email):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This account is not authorized for admin access.",
            )

    if _email_verification_required() and row.get("email_verified_at") is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Verify your email before signing in.",
        )

    if row.get("is_active") is False:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Account is deactivated.",
        )

    user_id = UUID(str(row["id"]))
    access, refresh, session_id = await _issue_tokens(
        user_id=user_id,
        email=row.get("email"),
        phone=row.get("phone"),
    )
    return _auth_response(_row_to_user(row), access), refresh, session_id


async def send_phone_otp(*, phone_digits: str) -> str | None:
    _ensure_phone_otp_enabled()
    try:
        return await create_and_send_otp(phone=phone_digits, purpose=OTP_PURPOSE_LOGIN)
    except OtpError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


async def verify_phone_otp(*, phone_digits: str, code: str) -> tuple[AuthResponse, str, str]:
    _ensure_phone_otp_enabled()
    try:
        await verify_otp_code(phone=phone_digits, code=code, purpose=OTP_PURPOSE_LOGIN)
    except OtpError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc

    sb = get_supabase()
    e164 = phone_e164(phone_digits)
    now = utcnow().isoformat()
    existing = (
        sb.table("users").select("*").eq("phone", e164).limit(1).execute()
    )
    if existing.data:
        row = existing.data[0]
        sb.table("users").update(
            {"phone_verified_at": now, "updated_at": now}
        ).eq("id", row["id"]).execute()
        row["phone_verified_at"] = now
    else:
        inserted = (
            sb.table("users")
            .insert(
                {
                    "phone": e164,
                    "phone_verified_at": now,
                    "updated_at": now,
                }
            )
            .execute()
        )
        if not inserted.data:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create user."
            )
        row = inserted.data[0]

    user_id = UUID(str(row["id"]))
    access, refresh, session_id = await _issue_tokens(
        user_id=user_id,
        email=row.get("email"),
        phone=e164,
    )
    return _auth_response(_row_to_user(row), access), refresh, session_id


async def verify_email_token(*, token: str) -> tuple[AuthResponse, str, str]:
    sb = get_supabase()
    token_hash = hash_token(token)
    result = (
        sb.table("password_reset_tokens")
        .select("*")
        .eq("token_hash", token_hash)
        .is_("used_at", "null")
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link.")

    record = result.data[0]
    now = utcnow()
    exp = record["expires_at"]
    if isinstance(exp, str):
        from datetime import datetime

        exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=now.tzinfo)
        if now > exp_dt:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link expired.")

    user_id = record["user_id"]
    sb.table("users").update(
        {
            "email_verified_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    ).eq("id", user_id).execute()
    sb.table("password_reset_tokens").update({"used_at": now.isoformat()}).eq(
        "id", record["id"]
    ).execute()

    user = sb.table("users").select("*").eq("id", user_id).limit(1).execute()
    if not user.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    row = user.data[0]
    row["email_verified_at"] = now.isoformat()

    uid = UUID(str(user_id))
    access, refresh, session_id = await _issue_tokens(
        user_id=uid,
        email=row.get("email"),
        phone=row.get("phone"),
    )
    return _auth_response(_row_to_user(row), access), refresh, session_id


async def refresh_session(*, refresh_token: str) -> tuple[AuthResponse, str, str]:
    try:
        payload = decode_refresh_token(refresh_token)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token.") from exc

    session_id = UUID(str(payload["sid"]))
    user_id = UUID(str(payload["sub"]))
    token_hash = hash_token(refresh_token)

    sb = get_supabase()
    session = (
        sb.table("refresh_sessions")
        .select("*")
        .eq("id", str(session_id))
        .eq("token_hash", token_hash)
        .is_("revoked_at", "null")
        .limit(1)
        .execute()
    )
    if not session.data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked or invalid.")

    session_row = session.data[0]
    now = utcnow()
    exp = session_row.get("expires_at")
    if exp is not None:
        if isinstance(exp, str):
            from datetime import datetime

            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=now.tzinfo)
        else:
            exp_dt = exp
        if now > exp_dt:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired.")

    user = sb.table("users").select("*").eq("id", str(user_id)).limit(1).execute()
    if not user.data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found.")

    row = user.data[0]
    _assert_user_accessible(
        email=row.get("email"),
        email_verified_at=row.get("email_verified_at"),
        is_active=bool(row.get("is_active", True)),
    )

    sb.table("refresh_sessions").update({"revoked_at": now.isoformat()}).eq(
        "id", str(session_id)
    ).execute()

    access, new_refresh, new_sid = await _issue_tokens(
        user_id=user_id,
        email=row.get("email"),
        phone=row.get("phone"),
    )
    return _auth_response(_row_to_user(row), access), new_refresh, new_sid


async def logout_session(*, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    try:
        payload = decode_refresh_token(refresh_token)
        session_id = str(payload["sid"])
    except Exception:
        return
    sb = get_supabase()
    sb.table("refresh_sessions").update({"revoked_at": utcnow().isoformat()}).eq(
        "id", session_id
    ).execute()


async def forgot_password(*, email: str) -> None:
    sb = get_supabase()
    result = (
        sb.table("users").select("id").eq("email", email.lower()).limit(1).execute()
    )
    if not result.data:
        return
    user_id = result.data[0]["id"]
    token = generate_opaque_token()
    now = utcnow()
    sb.table("password_reset_tokens").insert(
        {
            "user_id": user_id,
            "token_hash": hash_token(token),
            "expires_at": (now + timedelta(hours=PASSWORD_RESET_EXPIRE_HOURS)).isoformat(),
        }
    ).execute()
    await send_password_reset_email(to=email.lower(), token=token)


async def reset_password(*, token: str, password: str) -> None:
    sb = get_supabase()
    token_hash = hash_token(token)
    result = (
        sb.table("password_reset_tokens")
        .select("*")
        .eq("token_hash", token_hash)
        .is_("used_at", "null")
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset link.")

    record = result.data[0]
    now = utcnow()
    sb.table("users").update(
        {
            "password_hash": hash_password(password),
            "updated_at": now.isoformat(),
        }
    ).eq("id", record["user_id"]).execute()
    sb.table("password_reset_tokens").update({"used_at": now.isoformat()}).eq(
        "id", record["id"]
    ).execute()
    sb.table("refresh_sessions").update({"revoked_at": now.isoformat()}).eq(
        "user_id", record["user_id"]
    ).is_("revoked_at", "null").execute()


async def google_login_or_register(
    *, google_id: str, email: str, full_name: str | None
) -> GoogleLoginResult:
    sb = get_supabase()
    now = utcnow()
    email_lower = email.lower()
    skip_verify = not _email_verification_required()

    by_google = (
        sb.table("users").select("*").eq("google_id", google_id).limit(1).execute()
    )
    if by_google.data:
        row = by_google.data[0]
    else:
        by_email = (
            sb.table("users").select("*").eq("email", email_lower).limit(1).execute()
        )
        if by_email.data:
            row = by_email.data[0]
            update_payload: dict[str, Any] = {
                "google_id": google_id,
                "full_name": row.get("full_name") or full_name,
                "updated_at": now.isoformat(),
            }
            if skip_verify and row.get("email_verified_at") is None:
                update_payload["email_verified_at"] = now.isoformat()
            sb.table("users").update(update_payload).eq("id", row["id"]).execute()
            row = {**row, **update_payload}
        else:
            insert_payload: dict[str, Any] = {
                "email": email_lower,
                "full_name": full_name,
                "google_id": google_id,
                "updated_at": now.isoformat(),
            }
            if skip_verify:
                insert_payload["email_verified_at"] = now.isoformat()
            inserted = sb.table("users").insert(insert_payload).execute()
            if not inserted.data:
                raise HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "Could not create user.",
                )
            row = inserted.data[0]

    user_id = UUID(str(row["id"]))
    is_verified = row.get("email_verified_at") is not None

    if not is_verified:
        await _queue_email_verification(
            user_id=user_id, email=email_lower, full_name=full_name
        )
        check_email = (
            f"/check-email?email={email_lower}"
            if email_lower
            else "/check-email"
        )
        return GoogleLoginResult(
            pending_redirect_to=check_email,
            message="Check your email for a verification link to continue.",
        )

    access, refresh, session_id = await _issue_tokens(
        user_id=user_id,
        email=row.get("email"),
        phone=row.get("phone"),
    )
    return GoogleLoginResult(
        auth=_auth_response(_row_to_user(row), access),
        refresh_token=refresh,
        session_id=session_id,
    )


async def update_user_profile(
    *,
    user_id: UUID,
    body: UpdateProfileRequest,
) -> UpdateProfileResponse:
    sb = get_supabase()
    warnings: dict[str, str] = {}
    payload: dict[str, Any] = {
        "full_name": body.full_name.strip(),
        "target_band": body.target_band,
        "updated_at": utcnow().isoformat(),
    }
    if body.exam_date is not None:
        payload["exam_date"] = body.exam_date.strip() or None
    if body.ielts_purpose is not None:
        payload["ielts_purpose"] = body.ielts_purpose
    if body.ielts_goal is not None:
        payload["ielts_goal"] = body.ielts_goal

    raw_phone = (body.phone or "").strip()
    if not raw_phone:
        # DB trigger atomically clears verification/WhatsApp enablement iff changed.
        payload["phone"] = None
    else:
        digits = normalize_india_phone(raw_phone)
        if not is_valid_india_phone(digits):
            warnings["phone"] = "Enter a valid 10-digit Indian mobile number."
        else:
            e164 = phone_e164(digits)
            clash = (
                sb.table("users")
                .select("id")
                .eq("phone", e164)
                .neq("id", str(user_id))
                .limit(1)
                .execute()
            )
            if clash.data:
                warnings["phone"] = (
                    "This phone number is already linked to another account."
                )
                logger.info(
                    "PROFILE_PHONE_CONFLICT user_id=%s phone=%s",
                    user_id,
                    e164,
                )
            else:
                # DB trigger performs exact change detection in this same UPDATE.
                payload["phone"] = e164
    # on a warning, phone key is omitted -> existing value untouched

    sb.table("users").update(payload).eq("id", str(user_id)).execute()
    user = await get_user_by_id(user_id)
    return UpdateProfileResponse(user=user, warnings=warnings)


async def upload_user_avatar(
    *,
    user_id: UUID,
    content: bytes,
    content_type: str,
) -> UserPublic:
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Image must be 2 MB or smaller.",
        )
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if content_type not in allowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Use JPEG, PNG, or WebP.",
        )

    sniffed: str | None = None
    if content.startswith(b"\xff\xd8\xff"):
        sniffed = "image/jpeg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        sniffed = "image/png"
    elif len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        sniffed = "image/webp"
    if sniffed is None or sniffed != content_type:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "File content does not match a JPEG, PNG, or WebP image.",
        )

    ext = "jpg"
    if content_type == "image/png":
        ext = "png"
    elif content_type == "image/webp":
        ext = "webp"

    key = f"avatars/{user_id}.{ext}"
    sb = get_supabase()
    existing = (
        sb.table("users").select("avatar_url").eq("id", str(user_id)).limit(1).execute()
    )
    old_key = existing.data[0].get("avatar_url") if existing.data else None
    if old_key and old_key != key:
        delete_object(old_key)

    upload_object(key=key, body=content, content_type=content_type)
    sb.table("users").update(
        {"avatar_url": key, "updated_at": utcnow().isoformat()}
    ).eq("id", str(user_id)).execute()
    return await get_user_by_id(user_id)


async def get_user_by_id(user_id: UUID) -> UserPublic:
    sb = get_supabase()
    result = sb.table("users").select("*").eq("id", str(user_id)).limit(1).execute()
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    row = result.data[0]
    _assert_user_accessible(
        email=row.get("email"),
        email_verified_at=row.get("email_verified_at"),
        is_active=bool(row.get("is_active", True)),
    )
    return _row_to_user(row)


async def get_session_user_by_id(user_id: UUID) -> SessionUser:
    sb = get_supabase()
    result = (
        sb.table("users")
        .select(
            "id, full_name, email, role, avatar_url, is_active, email_verified_at, "
            "ielts_purpose, ielts_goal"
        )
        .eq("id", str(user_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    row = result.data[0]
    _assert_user_accessible(
        email=row.get("email"),
        email_verified_at=row.get("email_verified_at"),
        is_active=bool(row.get("is_active", True)),
    )
    return _row_to_session(row)


async def _issue_tokens(
    *,
    user_id: UUID,
    email: str | None,
    phone: str | None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, str, str]:
    sb = get_supabase()
    session_id = uuid4()
    refresh = create_refresh_token(user_id=user_id, session_id=session_id)
    refresh_hash = hash_token(refresh)
    now = utcnow()
    expires = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    sb.table("refresh_sessions").insert(
        {
            "id": str(session_id),
            "user_id": str(user_id),
            "token_hash": refresh_hash,
            "user_agent": user_agent,
            "ip_address": ip_address,
            "expires_at": expires.isoformat(),
        }
    ).execute()

    access = create_access_token(user_id=user_id, email=email, phone=phone)
    return access, refresh, str(session_id)
