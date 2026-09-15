"""Auth API router — register, login, me."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.tenant import TenantMembership
from app.models.user import User
from app.schemas.auth import TokenResponse, UserLogin, UserResponse
from app.services.auth import create_access_token, verify_password

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
