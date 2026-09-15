"""Tenant context — resolves the active tenant from the user's JWT token."""
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User


def get_current_tenant(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Tenant:
    """Resolve the user's active tenant. Raises 403 if user has no tenant."""
    tenant_id = current_user.active_tenant_id
    if not tenant_id:
        # Auto-select first membership if no active tenant set
        membership = db.query(TenantMembership).filter(
            TenantMembership.user_id == current_user.id
        ).first()
        if membership:
            current_user.active_tenant_id = membership.tenant_id
            db.commit()
            tenant_id = membership.tenant_id
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not a member of any tenant. Please contact your administrator.",
            )

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active tenant not found.",
        )
    if tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant '{tenant.name}' is {tenant.status}. Please contact support.",
        )

    # Verify membership
    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == current_user.id,
        TenantMembership.tenant_id == tenant.id,
    ).first()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have access to this tenant.",
        )

    return tenant


def get_tenant_role(
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> str:
    """Return the user's role within the current tenant."""
    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == current_user.id,
        TenantMembership.tenant_id == current_tenant.id,
    ).first()
    return membership.role if membership else "member"


def require_tenant_role(*allowed_roles):
    """Dependency factory: require the user to have one of the specified tenant roles."""
    def checker(
        current_user: User = Depends(get_current_user),
        current_tenant: Tenant = Depends(get_current_tenant),
        db: Session = Depends(get_db),
    ) -> User:
        membership = db.query(TenantMembership).filter(
            TenantMembership.user_id == current_user.id,
            TenantMembership.tenant_id == current_tenant.id,
        ).first()
        if not membership or membership.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of: {', '.join(allowed_roles)}",
            )
        return current_user
    return checker
