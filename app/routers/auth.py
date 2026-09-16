"""Auth API router — register, login, me, password reset."""
import secrets as _secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

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
    UserResponse,
)
from app.services.auth import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """Login and get a JWT access token."""
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
    """Request a password reset token.

    Always returns 200 (even if email doesn't exist) to prevent email enumeration.
    In production, this would send an email with the reset link.
    For local dev, the reset token is returned in the response.
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

    # In production: send email with link to /reset-password?token=xxx
    # For local dev: return the token so the UI can redirect directly
    return {
        "message": "Reset token generated.",
        "reset_token": raw_token,
        "email": user.email,
    }


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
