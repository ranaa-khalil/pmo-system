"""Auth API router — register, login, me, password reset."""
import secrets as _secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.password_reset_token import PasswordResetToken
from app.models.tenant import TenantMembership
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserLogin,
    ValidateTokenRequest,
)
from app.services.auth import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Login brute-force protection
# ---------------------------------------------------------------------------
# /api/auth/login is excluded from the global per-tenant rate limiter (auth
# happens before a tenant context exists), so login gets its own limiter:
# per-IP and per-account sliding windows with 429 + Retry-After.
import time as _time
from collections import defaultdict as _defaultdict

from fastapi import Request as _Request

LOGIN_MAX_ATTEMPTS = 8          # attempts per window per IP
LOGIN_ACCOUNT_MAX = 5           # attempts per window per account
LOGIN_WINDOW_SECONDS = 300      # 5 minutes
LOGIN_LOCKOUT_SECONDS = 900     # 15 minutes after limit hit

_login_ip_attempts: dict[str, list[float]] = _defaultdict(list)
_login_account_attempts: dict[str, list[float]] = _defaultdict(list)


def _prune(bucket: dict[str, list[float]], key: str, now: float) -> list[float]:
    cutoff = now - LOGIN_WINDOW_SECONDS
    bucket[key] = [ts for ts in bucket[key] if ts > cutoff]
    return bucket[key]


def _check_login_limit(bucket: dict[str, list[float]], key: str, max_attempts: int) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds)."""
    now = _time.time()
    attempts = _prune(bucket, key, now)
    if len(attempts) >= max_attempts:
        oldest = min(attempts)
        # Escalate: once over the limit, lock out for the full lockout period
        retry_after = max(1, int(oldest + LOGIN_LOCKOUT_SECONDS - now))
        return False, retry_after
    attempts.append(now)
    return True, 0


def _client_ip(request: _Request | None) -> str:
    if request is None:
        return "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=TokenResponse)
def login(
    credentials: UserLogin,
    db: Session = Depends(get_db),
    request: _Request = None,
):
    """Login and get a JWT access token."""
    ip = _client_ip(request)
    email_key = (credentials.email or "").strip().lower()
    allowed_ip, retry_ip = _check_login_limit(_login_ip_attempts, ip, LOGIN_MAX_ATTEMPTS)
    allowed_acct, retry_acct = _check_login_limit(_login_account_attempts, email_key, LOGIN_ACCOUNT_MAX)
    if not allowed_ip or not allowed_acct:
        retry_after = max(retry_ip, retry_acct)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user or not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token(data={"sub": str(user.id)})
    return TokenResponse(access_token=token)


@router.get("/me")
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the current authenticated user."""
    from app.models.tenant import TenantMembership
    # Get the user's role in their active tenant
    tenant_role = None
    if current_user.active_tenant_id:
        membership = db.query(TenantMembership).filter(
            TenantMembership.user_id == current_user.id,
            TenantMembership.tenant_id == current_user.active_tenant_id,
        ).first()
        if membership:
            tenant_role = membership.role

    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.name,
        "name": current_user.name,
        "system_role": current_user.system_role,
        "tenant_role": tenant_role,
        "is_active": current_user.is_active,
        "active_tenant_id": current_user.active_tenant_id,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.get("/me/tenants")
def get_my_tenants(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all tenants the current user belongs to."""
    memberships = db.query(TenantMembership).filter(
        TenantMembership.user_id == current_user.id
    ).all()
    result = []
    for m in memberships:
        tenant = m.tenant
        result.append({
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "plan": tenant.plan,
            "role": m.role,
            "is_active": current_user.active_tenant_id == tenant.id,
        })
    return result


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Request a password reset link via email.

    Always returns 200 (even if email doesn't exist) to prevent email enumeration.
    Sends an email with a reset link to the user if the account exists.
    """
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        return {"message": "If an account with that email exists, a reset link has been sent."}

    # Invalidate any previous unused tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == False,
    ).update({"used": True})

    # Generate a secure token
    raw_token = _secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    reset_token = PasswordResetToken(
        user_id=user.id,
        token=raw_token,
        expires_at=expires_at,
        used=False,
    )
    db.add(reset_token)
    db.commit()

    # Send the reset email
    from app.services.email import send_password_reset_email
    email_sent = send_password_reset_email(user.email, raw_token, user.name)

    if not email_sent:
        # Email delivery failed — still show "check your email" to the user
        # (don't leak the token in the API response).
        # Log the reset link to the server console for dev/testing.
        reset_url = f"{settings.app_url}/?reset_token={raw_token}"
        print(f"[password-reset] Email send failed for {user.email}.")
        print(f"[password-reset] Dev reset link: {reset_url}")

    return {"message": "A password reset link has been sent to your email."}


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password using a valid token."""
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == req.token,
        PasswordResetToken.used == False,
    ).first()

    if not reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if reset_token.expires_at < datetime.now(UTC):
        reset_token.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="Reset token has expired")

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")

    user.hashed_password = hash_password(req.new_password)
    reset_token.used = True
    db.commit()

    return {"message": "Password has been reset successfully. You can now log in with your new password."}


@router.post("/validate-reset-token")
def validate_reset_token(req: ValidateTokenRequest, db: Session = Depends(get_db)):
    """Validate a reset token without resetting the password."""
    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == req.token,
        PasswordResetToken.used == False,
    ).first()

    if not reset_token:
        return {"valid": False, "message": "Invalid or expired reset token"}

    if reset_token.expires_at < datetime.now(UTC):
        reset_token.used = True
        db.commit()
        return {"valid": False, "message": "Reset token has expired"}

    return {"valid": True}
