"""Tenant management router — registration, team management, invitations."""
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import Project
from app.models.tenant import (
    MEMBER_ROLE_ADMIN,
    MEMBER_ROLE_MEMBER,
    MEMBER_ROLE_OWNER,
    PLAN_LIMITS,
    Invitation,
    Tenant,
    TenantMembership,
)
from app.models.user import User
from app.schemas.tenant import (
    AcceptInviteRequest,
    InvitationResponse,
    InviteRequest,
    RegisterRequest,
    SwitchTenantRequest,
    TenantMembershipResponse,
    TenantResponse,
    TenantUpdate,
    UsageResponse,
)
from app.services.auth import create_access_token, hash_password
from app.services.tenant import get_current_tenant, require_tenant_role

router = APIRouter(prefix="/api", tags=["tenant"])


def _slugify(name: str) -> str:
    """Convert a company name to a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower().strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "tenant"


def _unique_slug(db: Session, name: str) -> str:
    """Generate a unique slug for a tenant."""
    base = _slugify(name)
    slug = base
    n = 2
    while db.query(Tenant).filter(Tenant.slug == slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


# ─── Registration ───────────────────────────────────────────

@router.post("/auth/register", response_model=dict, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Self-service registration: creates a tenant + owner user."""
    # Check if email already exists
    existing = db.query(User).filter(User.email == req.email.lower()).first()
    if existing:
        raise HTTPException(400, "An account with this email already exists. Please log in.")

    # Create tenant
    slug = _unique_slug(db, req.tenant_name)
    tenant = Tenant(name=req.tenant_name, slug=slug, plan="free", status="active")
    db.add(tenant)
    db.flush()  # get tenant.id

    # Create user
    user = User(
        email=req.email.lower(),
        name=req.name,
        hashed_password=hash_password(req.password),
        system_role="member",
        is_active=True,
        active_tenant_id=tenant.id,
    )
    db.add(user)
    db.flush()  # get user.id

    # Create owner membership
    membership = TenantMembership(
        user_id=user.id,
        tenant_id=tenant.id,
        role=MEMBER_ROLE_OWNER,
    )
    db.add(membership)
    db.commit()

    # Generate token
    token = create_access_token({"sub": str(user.id)})
    return {
        "token": token,
        "token_type": "bearer",
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "user_id": user.id,
        "user_name": user.name,
    }


# ─── Tenant Info ────────────────────────────────────────────

@router.get("/tenant", response_model=TenantResponse)
def get_tenant(
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get the current tenant's info."""
    return current_tenant


@router.put("/tenant", response_model=TenantResponse)
def update_tenant(
    req: TenantUpdate,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Update tenant info (owner/admin only)."""
    if req.name is not None:
        current_tenant.name = req.name
    if req.logo_url is not None:
        current_tenant.logo_url = req.logo_url
    db.commit()
    db.refresh(current_tenant)
    return current_tenant


@router.post("/auth/switch-tenant", response_model=dict)
def switch_tenant(
    req: SwitchTenantRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Switch the active tenant for the current user."""
    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == current_user.id,
        TenantMembership.tenant_id == req.tenant_id,
    ).first()
    if not membership:
        raise HTTPException(403, "You are not a member of this tenant.")

    tenant = db.query(Tenant).filter(Tenant.id == req.tenant_id).first()
    if not tenant or tenant.status != "active":
        raise HTTPException(403, "Tenant is not available.")

    current_user.active_tenant_id = req.tenant_id
    db.commit()

    return {"tenant_id": tenant.id, "tenant_name": tenant.name, "role": membership.role}


@router.get("/auth/my-tenants", response_model=list[TenantResponse])
def list_my_tenants(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all tenants the current user belongs to."""
    memberships = db.query(TenantMembership).filter(
        TenantMembership.user_id == current_user.id
    ).all()
    tenant_ids = [m.tenant_id for m in memberships]
    tenants = db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).all()
    return tenants


# ─── Team Management ────────────────────────────────────────

@router.get("/tenant/members", response_model=list[TenantMembershipResponse])
def list_members(
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List all members of the current tenant."""
    memberships = db.query(TenantMembership).filter(
        TenantMembership.tenant_id == current_tenant.id
    ).all()
    result = []
    for m in memberships:
        user = db.query(User).filter(User.id == m.user_id).first()
        result.append(TenantMembershipResponse(
            id=m.id,
            user_id=m.user_id,
            tenant_id=m.tenant_id,
            role=m.role,
            joined_at=m.joined_at,
            user_email=user.email if user else "",
            user_name=user.name if user else "",
        ))
    return result


@router.post("/tenant/invite", response_model=InvitationResponse, status_code=201)
def create_invitation(
    req: InviteRequest,
    current_tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Invite a new member to the tenant (owner/admin only)."""
    # Check quota
    limits = PLAN_LIMITS.get(current_tenant.plan, PLAN_LIMITS["free"])
    current_count = db.query(TenantMembership).filter(
        TenantMembership.tenant_id == current_tenant.id
    ).count()
    if current_count >= limits["users"]:
        raise HTTPException(403, f"User limit reached for {current_tenant.plan} plan ({limits['users']} users). Upgrade to add more.")

    # Check if already invited
    existing = db.query(Invitation).filter(
        Invitation.tenant_id == current_tenant.id,
        Invitation.email == req.email.lower(),
        Invitation.status == "pending",
    ).first()
    if existing:
        raise HTTPException(400, "An invitation has already been sent to this email.")

    # Check if already a member
    existing_user = db.query(User).filter(User.email == req.email.lower()).first()
    if existing_user:
        existing_membership = db.query(TenantMembership).filter(
            TenantMembership.user_id == existing_user.id,
            TenantMembership.tenant_id == current_tenant.id,
        ).first()
        if existing_membership:
            raise HTTPException(400, "This user is already a member of the tenant.")

    invitation = Invitation(
        tenant_id=current_tenant.id,
        email=req.email.lower(),
        role=req.role,
        token=Invitation.generate_token(),
        invited_by=current_user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation


@router.post("/tenant/accept-invite", response_model=dict)
def accept_invitation(req: AcceptInviteRequest, db: Session = Depends(get_db)):
    """Accept an invitation and create a new user account."""
    invitation = db.query(Invitation).filter(
        Invitation.token == req.token,
        Invitation.status == "pending",
    ).first()
    if not invitation:
        raise HTTPException(400, "Invalid or expired invitation token.")

    # Check expiry (handle both tz-aware and tz-naive datetimes)
    now = datetime.now(UTC)
    expires = invitation.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if now > expires:
        invitation.status = "expired"
        db.commit()
        raise HTTPException(400, "This invitation has expired. Please ask your administrator to resend it.")

    # Check if user already exists
    user = db.query(User).filter(User.email == invitation.email).first()
    if not user:
        user = User(
            email=invitation.email,
            name=req.name,
            hashed_password=hash_password(req.password),
            system_role="member",
            is_active=True,
            active_tenant_id=invitation.tenant_id,
        )
        db.add(user)
        db.flush()
    else:
        user.active_tenant_id = invitation.tenant_id

    # Create membership
    membership = TenantMembership(
        user_id=user.id,
        tenant_id=invitation.tenant_id,
        role=invitation.role,
    )
    db.add(membership)

    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(UTC)
    db.commit()

    token = create_access_token({"sub": str(user.id)})
    tenant = db.query(Tenant).filter(Tenant.id == invitation.tenant_id).first()
    return {
        "token": token,
        "token_type": "bearer",
        "tenant_id": tenant.id,
        "tenant_name": tenant.name if tenant else "",
        "user_id": user.id,
        "user_name": user.name,
    }


@router.delete("/tenant/members/{user_id}", status_code=204)
def remove_member(
    user_id: int,
    current_tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Remove a member from the tenant (owner/admin only)."""
    if user_id == current_user.id:
        raise HTTPException(400, "You cannot remove yourself. Transfer ownership first.")

    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == user_id,
        TenantMembership.tenant_id == current_tenant.id,
    ).first()
    if not membership:
        raise HTTPException(404, "Member not found in this tenant.")

    # Don't allow removing the last owner
    if membership.role == MEMBER_ROLE_OWNER:
        owner_count = db.query(TenantMembership).filter(
            TenantMembership.tenant_id == current_tenant.id,
            TenantMembership.role == MEMBER_ROLE_OWNER,
        ).count()
        if owner_count <= 1:
            raise HTTPException(400, "Cannot remove the last owner of the tenant.")

    db.delete(membership)
    db.commit()


@router.put("/tenant/members/{user_id}", response_model=TenantMembershipResponse)
def change_member_role(
    user_id: int,
    role: str,
    current_tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER)),
    db: Session = Depends(get_db),
):
    """Change a member's role (owner only)."""
    if role not in (MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN, MEMBER_ROLE_MEMBER):
        raise HTTPException(400, f"Invalid role. Must be one of: {MEMBER_ROLE_OWNER}, {MEMBER_ROLE_ADMIN}, {MEMBER_ROLE_MEMBER}")

    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == user_id,
        TenantMembership.tenant_id == current_tenant.id,
    ).first()
    if not membership:
        raise HTTPException(404, "Member not found in this tenant.")

    membership.role = role
    db.commit()
    db.refresh(membership)

    user = db.query(User).filter(User.id == membership.user_id).first()
    return TenantMembershipResponse(
        id=membership.id,
        user_id=membership.user_id,
        tenant_id=membership.tenant_id,
        role=membership.role,
        joined_at=membership.joined_at,
        user_email=user.email if user else "",
        user_name=user.name if user else "",
    )


@router.get("/tenant/invitations", response_model=list[InvitationResponse])
def list_invitations(
    current_tenant: Tenant = Depends(get_current_tenant),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """List pending invitations for the tenant."""
    return db.query(Invitation).filter(
        Invitation.tenant_id == current_tenant.id,
        Invitation.status == "pending",
    ).all()


@router.delete("/tenant/invitations/{invitation_id}", status_code=204)
def revoke_invitation(
    invitation_id: int,
    current_tenant: Tenant = Depends(get_current_tenant),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Revoke a pending invitation."""
    invitation = db.query(Invitation).filter(
        Invitation.id == invitation_id,
        Invitation.tenant_id == current_tenant.id,
    ).first()
    if not invitation:
        raise HTTPException(404, "Invitation not found.")
    invitation.status = "revoked"
    db.commit()


# ─── Usage & Quotas ─────────────────────────────────────────

@router.get("/tenant/usage", response_model=UsageResponse)
def get_usage(
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get current usage metrics for the tenant."""
    limits = PLAN_LIMITS.get(current_tenant.plan, PLAN_LIMITS["free"])
    user_count = db.query(TenantMembership).filter(
        TenantMembership.tenant_id == current_tenant.id
    ).count()
    project_count = db.query(Project).filter(
        Project.tenant_id == current_tenant.id
    ).count()
    return UsageResponse(
        plan=current_tenant.plan,
        users=user_count,
        users_limit=limits["users"],
        projects=project_count,
        projects_limit=limits["projects"],
    )
