"""Tenant management router — admin tenant creation, team management, invitations."""
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, EmailStr, Field
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
    AdminCreateUserRequest,
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


# ─── Admin: Create Tenant (super_admin only, replaces self-registration) ───

class CreateTenantRequest(BaseModel):
    tenant_name: str = Field(..., min_length=1, max_length=255)
    owner_name: str = Field(..., min_length=1, max_length=255)
    owner_email: EmailStr
    owner_password: str = Field(..., min_length=8, max_length=72)
    plan: str = Field("free", pattern=r"^(free|team|business|enterprise)$")


@router.post("/admin/tenants", status_code=201)
def create_tenant(
    req: CreateTenantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new tenant with an owner user (super_admin only).

    Replaces self-registration — only the super admin can create new tenants.
    """
    _require_super_admin(current_user)

    # Check if email already exists
    existing = db.query(User).filter(User.email == req.owner_email.lower()).first()
    if existing:
        raise HTTPException(400, f"An account with email {req.owner_email} already exists.")

    # Create tenant
    slug = _unique_slug(db, req.tenant_name)
    tenant = Tenant(name=req.tenant_name, slug=slug, plan=req.plan, status="active")
    db.add(tenant)
    db.flush()

    # Create owner user
    user = User(
        email=req.owner_email.lower(),
        name=req.owner_name,
        hashed_password=hash_password(req.owner_password),
        system_role="member",
        is_active=True,
        active_tenant_id=tenant.id,
    )
    db.add(user)
    db.flush()

    # Create owner membership
    membership = TenantMembership(
        user_id=user.id,
        tenant_id=tenant.id,
        role="owner",
    )
    db.add(membership)
    db.commit()

    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
        "plan": tenant.plan,
        "owner_user_id": user.id,
        "owner_email": user.email,
        "message": f"Tenant '{tenant.name}' created with owner {user.email}.",
    }


@router.post("/admin/tenants/{tenant_id}/users", status_code=201)
def admin_create_user(
    tenant_id: int,
    req: AdminCreateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a user directly in a tenant (super_admin only, no invite flow)."""
    _require_super_admin(current_user)

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")

    existing = db.query(User).filter(User.email == req.email.lower()).first()
    if existing:
        raise HTTPException(400, f"An account with email {req.email} already exists.")

    user = User(
        email=req.email.lower(),
        name=req.name,
        hashed_password=hash_password(req.password),
        system_role="member",
        is_active=True,
        active_tenant_id=tenant_id,
    )
    db.add(user)
    db.flush()

    role = req.role if req.role in ("owner", "admin", "member") else "member"
    membership = TenantMembership(user_id=user.id, tenant_id=tenant_id, role=role)
    db.add(membership)
    db.commit()

    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "role": role,
        "tenant_id": tenant_id,
        "message": f"User {user.email} added to {tenant.name} as {role}.",
    }


# ─── Tenant info & management ───────────────────────────────


# ─── Tenant Info ────────────────────────────────────────────

@router.get("/tenant", response_model=TenantResponse)
def get_tenant(
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get the current tenant's info."""
    import json as _json
    resp = {
        "id": current_tenant.id,
        "name": current_tenant.name,
        "slug": current_tenant.slug,
        "plan": current_tenant.plan,
        "status": current_tenant.status,
        "logo_url": current_tenant.logo_url,
        "branding": _json.loads(current_tenant.branding) if current_tenant.branding else {},
        "created_at": current_tenant.created_at.isoformat() if current_tenant.created_at else None,
    }
    return resp


@router.put("/tenant", response_model=TenantResponse)
def update_tenant(
    req: TenantUpdate,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Update tenant info (owner/admin only)."""
    import json as _json
    if req.name is not None:
        current_tenant.name = req.name
    if req.logo_url is not None:
        current_tenant.logo_url = req.logo_url
    db.commit()
    db.refresh(current_tenant)
    return {
        "id": current_tenant.id,
        "name": current_tenant.name,
        "slug": current_tenant.slug,
        "plan": current_tenant.plan,
        "status": current_tenant.status,
        "logo_url": current_tenant.logo_url,
        "branding": _json.loads(current_tenant.branding) if current_tenant.branding else {},
        "created_at": current_tenant.created_at.isoformat() if current_tenant.created_at else None,
    }


@router.put("/tenant/branding")
def update_tenant_branding(
    req: dict,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Update tenant branding (available to all plans).

    Branding fields: primary_color (hex), logo_url, app_name, hide_powered_by (bool)
    hide_powered_by requires Enterprise plan.
    """
    import json as _json

    branding = _json.loads(current_tenant.branding) if current_tenant.branding else {}
    for key in ("primary_color", "logo_url", "app_name"):
        if key in req:
            branding[key] = req[key]
    # hide_powered_by is Enterprise only
    if "hide_powered_by" in req:
        if current_tenant.plan == "enterprise":
            branding["hide_powered_by"] = req["hide_powered_by"]
    # Also update logo_url column
    if "logo_url" in req:
        current_tenant.logo_url = req["logo_url"]
    current_tenant.branding = _json.dumps(branding)
    db.commit()
    return {"ok": True, "branding": branding}


@router.put("/admin/tenants/{tenant_id}/branding")
def admin_update_tenant_branding(
    tenant_id: int,
    req: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update tenant branding (super_admin only).

    Branding fields: primary_color, logo_url, app_name, hide_powered_by
    """
    _require_super_admin(current_user)

    import json as _json2
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")

    branding = _json2.loads(tenant.branding) if tenant.branding else {}
    for key in ("primary_color", "logo_url", "app_name", "hide_powered_by"):
        if key in req:
            branding[key] = req[key]
    # Also update the logo_url column directly if provided
    if "logo_url" in req:
        tenant.logo_url = req["logo_url"]
    tenant.branding = _json2.dumps(branding)
    db.commit()
    return {"ok": True, "branding": branding}


# ---- Logo upload endpoints ----

_LOGO_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "logos"
_LOGO_URL_PREFIX = "/uploads/logos"
_ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/svg+xml", "image/webp", "image/gif"}
_LOGO_MAX_SIZE = 2 * 1024 * 1024  # 2 MB


def _save_logo(file: UploadFile, tenant_id: int) -> str:
    """Save an uploaded logo and return the URL path."""
    import uuid

    # Validate content type
    ct = file.content_type or ""
    if ct not in _ALLOWED_LOGO_TYPES:
        raise HTTPException(400, f"Unsupported file type '{ct}'. Use PNG, JPEG, SVG, WebP, or GIF.")

    # Read and check size
    data = file.file.read()
    if len(data) > _LOGO_MAX_SIZE:
        raise HTTPException(400, "Logo file too large (max 2 MB).")

    # Determine extension
    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/svg+xml": ".svg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    ext = ext_map.get(ct, ".png")

    _LOGO_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"tenant-{tenant_id}-{uuid.uuid4().hex[:8]}{ext}"
    filepath = _LOGO_DIR / filename
    filepath.write_bytes(data)

    return f"/uploads/logos/{filename}"


@router.post("/tenant/logo")
def upload_tenant_logo(
    file: UploadFile = File(...),
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Upload a logo file for the current tenant (owner/admin only)."""
    import json as _json

    logo_url = _save_logo(file, current_tenant.id)
    current_tenant.logo_url = logo_url
    # Also store in branding JSON
    branding = _json.loads(current_tenant.branding) if current_tenant.branding else {}
    branding["logo_url"] = logo_url
    current_tenant.branding = _json.dumps(branding)
    db.commit()

    return {"ok": True, "logo_url": logo_url}


@router.post("/admin/tenants/{tenant_id}/logo")
def admin_upload_tenant_logo(
    tenant_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a logo for a specific tenant (super_admin only)."""
    _require_super_admin(current_user)
    import json as _json

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")

    logo_url = _save_logo(file, tenant.id)
    tenant.logo_url = logo_url
    branding = _json.loads(tenant.branding) if tenant.branding else {}
    branding["logo_url"] = logo_url
    tenant.branding = _json.dumps(branding)
    db.commit()

    return {"ok": True, "logo_url": logo_url}


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


# ─── Tenant Limits ───────────────────────────────────────────

@router.get("/tenant/limits")
def get_tenant_limits(
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get the current tenant's resource limits and usage."""
    import json as _json
    limits = _json.loads(current_tenant.limits) if current_tenant.limits else {}
    max_users = limits.get("max_users", 999999)
    max_projects = limits.get("max_projects", 999999)

    from app.services.usage_service import get_usage_counts
    counts = get_usage_counts(db, current_tenant.id)

    return {
        "limits": {"max_users": max_users, "max_projects": max_projects},
        "current": {
            "users": counts.get("users", 0),
            "projects": counts.get("projects", 0),
        },
    }


@router.put("/admin/tenants/{tenant_id}/limits")
def admin_update_tenant_limits(
    tenant_id: int,
    req: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update tenant resource limits (super admin only).

    Fields: max_users (int), max_projects (int)
    """
    _require_super_admin(current_user)
    import json as _json
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")

    limits = _json.loads(tenant.limits) if tenant.limits else {}

    if "max_users" in req:
        val = req["max_users"]
        limits["max_users"] = int(val) if val and int(val) > 0 else 999999
    if "max_projects" in req:
        val = req["max_projects"]
        limits["max_projects"] = int(val) if val and int(val) > 0 else 999999

    tenant.limits = _json.dumps(limits)
    db.commit()
    return {"ok": True, "limits": limits}


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
            is_active=user.is_active if user else True,
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
    from app.services.usage_service import check_quota, METRIC_USERS
    check_quota(db, current_tenant, METRIC_USERS)

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
    from app.services.usage_service import get_usage_counts, get_limits, METRIC_USERS, METRIC_PROJECTS
    counts = get_usage_counts(db, current_tenant.id)
    limits = get_limits(current_tenant)
    return UsageResponse(
        plan=current_tenant.plan,
        users=counts[METRIC_USERS],
        users_limit=limits[METRIC_USERS],
        projects=counts[METRIC_PROJECTS],
        projects_limit=limits[METRIC_PROJECTS],
    )


@router.get("/tenant/usage/history")
def get_usage_history_endpoint(
    days: int = 30,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Get usage history for the last N days (for charts)."""
    from app.services.usage_service import get_usage_history, get_usage_counts, get_limits
    history = get_usage_history(db, current_tenant.id, days)
    counts = get_usage_counts(db, current_tenant.id)
    limits = get_limits(current_tenant)
    return {
        "current": counts,
        "limits": limits,
        "history": history,
    }


# ─── Per-Tenant Settings (Integrations) ──────────────────────

@router.get("/tenant/settings")
def get_tenant_settings(
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Get all per-tenant settings (secrets are masked)."""
    from app.services.settings_service import get_all_settings
    return get_all_settings(db, current_tenant.id)


@router.put("/tenant/settings")
def update_tenant_settings(
    req: dict,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Update per-tenant settings (GitHub token, AI config, etc.).

    Accepts a dict of key-value pairs. Secret keys (github_token, ai_api_key)
    are encrypted at rest. Empty values clear the setting.
    """
    from app.models.tenant_setting import SECRET_KEYS
    from app.services.settings_service import set_setting, delete_setting

    updated = []
    for key, value in req.items():
        if key not in SECRET_KEYS and key not in ("ai_base_url", "ai_model"):
            continue  # Only allow known setting keys
        if value:
            set_setting(db, current_tenant.id, key, str(value))
            updated.append(key)
        else:
            delete_setting(db, current_tenant.id, key)
            updated.append(f"{key} (cleared)")

    db.commit()
    return {"ok": True, "updated": updated}


@router.delete("/tenant/settings/{key}")
def delete_tenant_setting(
    key: str,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Delete a per-tenant setting."""
    from app.services.settings_service import delete_setting
    deleted = delete_setting(db, current_tenant.id, key)
    db.commit()
    if not deleted:
        raise HTTPException(404, f"Setting '{key}' not found.")
    return {"ok": True, "deleted": key}


# ─── Admin: Tenant Management (super_admin only) ────────────

def _require_super_admin(user: User):
    if user.system_role != "super_admin":
        raise HTTPException(403, "Super admin access required.")


@router.get("/admin/tenants")
def list_all_tenants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all tenants (super_admin only)."""
    _require_super_admin(current_user)
    tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "slug": t.slug,
            "plan": t.plan,
            "status": t.status,
            "logo_url": t.logo_url,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "member_count": db.query(TenantMembership).filter(TenantMembership.tenant_id == t.id).count(),
            "project_count": db.query(Project).filter(Project.tenant_id == t.id).count(),
        }
        for t in tenants
    ]


@router.put("/admin/tenants/{tenant_id}/plan")
def update_tenant_plan(
    tenant_id: int,
    plan: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a tenant's plan (super_admin only).

    Plans: free, team, business, enterprise
    """
    _require_super_admin(current_user)
    if plan not in ("free", "team", "business", "enterprise"):
        raise HTTPException(400, "Invalid plan. Use: free, team, business, or enterprise.")

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")

    old_plan = tenant.plan
    tenant.plan = plan
    db.commit()
    return {
        "ok": True,
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "old_plan": old_plan,
        "new_plan": plan,
    }


@router.put("/admin/tenants/{tenant_id}/status")
def update_tenant_status(
    tenant_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a tenant's status (super_admin only).

    Statuses: active, suspended, cancelled
    """
    _require_super_admin(current_user)
    if status not in ("active", "suspended", "cancelled"):
        raise HTTPException(400, "Invalid status. Use: active, suspended, or cancelled.")

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")

    tenant.status = status
    db.commit()
    return {
        "ok": True,
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "status": status,
    }


@router.get("/admin/insights")
def get_admin_insights(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get system-wide insights (super_admin only).

    Returns aggregate stats across all tenants.
    """
    _require_super_admin(current_user)

    from app.models.backlog_item import BacklogItem
    from app.models.project import Project
    from app.models.release import Release
    from app.models.api_key import ApiKey

    tenants = db.query(Tenant).all()
    active_tenants = [t for t in tenants if t.status == "active"]
    suspended = [t for t in tenants if t.status == "suspended"]
    cancelled = [t for t in tenants if t.status == "cancelled"]

    total_members = db.query(TenantMembership).count()
    total_projects = db.query(Project).count()
    total_backlog = db.query(BacklogItem).count()
    total_releases = db.query(Release).count()
    total_api_keys = db.query(ApiKey).count()

    # Plan distribution
    plans = {"free": 0, "team": 0, "business": 0, "enterprise": 0}
    for t in tenants:
        plans[t.plan] = plans.get(t.plan, 0) + 1

    # Per-tenant breakdown
    tenant_details = []
    for t in tenants:
        members = db.query(TenantMembership).filter(TenantMembership.tenant_id == t.id).count()
        projects = db.query(Project).filter(Project.tenant_id == t.id).count()
        backlog = db.query(BacklogItem).filter(BacklogItem.tenant_id == t.id).count()
        releases = db.query(Release).filter(Release.tenant_id == t.id).count()
        tenant_details.append({
            "id": t.id,
            "name": t.name,
            "slug": t.slug,
            "plan": t.plan,
            "status": t.status,
            "members": members,
            "projects": projects,
            "backlog_items": backlog,
            "releases": releases,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {
        "totals": {
            "tenants": len(tenants),
            "active_tenants": len(active_tenants),
            "suspended_tenants": len(suspended),
            "cancelled_tenants": len(cancelled),
            "members": total_members,
            "projects": total_projects,
            "backlog_items": total_backlog,
            "releases": total_releases,
            "api_keys": total_api_keys,
        },
        "plan_distribution": plans,
        "tenants": tenant_details,
    }


# ─── Admin: Tenant Detail (super_admin only) ─────────────────

@router.get("/admin/tenants/{tenant_id}")
def get_tenant_detail(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed info about a specific tenant (super_admin only)."""
    _require_super_admin(current_user)

    import json as _json
    from app.models.backlog_item import BacklogItem
    from app.models.project import Project
    from app.models.release import Release
    from app.models.api_key import ApiKey

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found.")

    # Members with user details
    memberships = db.query(TenantMembership).filter(
        TenantMembership.tenant_id == tenant_id
    ).all()
    members = []
    for m in memberships:
        u = db.query(User).filter(User.id == m.user_id).first()
        if u:
            members.append({
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "role": m.role,
                "is_active": u.is_active,
                "system_role": u.system_role,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            })

    # Projects
    projects = db.query(Project).filter(Project.tenant_id == tenant_id).all()
    project_list = []
    for p in projects:
        project_list.append({
            "id": p.id,
            "name": p.name,
            "status": getattr(p, "status", "unknown"),
            "client_id": getattr(p, "client_id", None),
        })

    # Stats
    backlog_count = db.query(BacklogItem).filter(BacklogItem.tenant_id == tenant_id).count()
    release_count = db.query(Release).filter(Release.tenant_id == tenant_id).count()
    api_key_count = db.query(ApiKey).filter(ApiKey.tenant_id == tenant_id).count()

    # Settings
    from app.models.tenant_setting import TenantSetting
    settings_list = db.query(TenantSetting).filter(TenantSetting.tenant_id == tenant_id).all()
    settings_keys = [{"key": s.key, "is_secret": s.is_secret} for s in settings_list]

    return {
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "plan": tenant.plan,
            "status": tenant.status,
            "branding": _json.loads(tenant.branding) if tenant.branding else {},
            "logo_url": tenant.logo_url or (_json.loads(tenant.branding).get("logo_url", "") if tenant.branding else ""),
            "limits": _json.loads(tenant.limits) if tenant.limits else {"max_users": 999999, "max_projects": 999999},
            "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        },
        "members": members,
        "projects": project_list,
        "stats": {
            "member_count": len(members),
            "project_count": len(project_list),
            "backlog_items": backlog_count,
            "releases": release_count,
            "api_keys": api_key_count,
            "settings": len(settings_keys),
        },
        "settings_keys": settings_keys,
    }


@router.post("/admin/tenants/{tenant_id}/members")
def admin_add_member(
    tenant_id: int,
    name: str = "",
    email: str = "",
    password: str = "",
    role: str = "member",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a user to a tenant (super_admin only)."""
    _require_super_admin(current_user)

    if not email or not password:
        raise HTTPException(400, "Email and password are required.")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        # User already exists — add membership if not already a member
        mem = db.query(TenantMembership).filter(
            TenantMembership.user_id == existing.id,
            TenantMembership.tenant_id == tenant_id,
        ).first()
        if mem:
            raise HTTPException(400, "User is already a member of this tenant.")
        db.add(TenantMembership(user_id=existing.id, tenant_id=tenant_id, role=role))
        db.commit()
        return {"ok": True, "message": f"Added existing user {email} to tenant."}

    new_user = User(
        email=email,
        name=name or email.split("@")[0],
        hashed_password=hash_password(password),
        system_role="member",
        is_active=True,
        active_tenant_id=tenant_id,
    )
    db.add(new_user)
    db.flush()
    db.add(TenantMembership(user_id=new_user.id, tenant_id=tenant_id, role=role))
    db.commit()
    return {"ok": True, "user_id": new_user.id, "message": f"Created user {email}."}


@router.put("/admin/tenants/{tenant_id}/members/{user_id}")
def admin_update_member(
    tenant_id: int,
    user_id: int,
    role: str = "",
    is_active: bool = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a tenant member (super_admin only)."""
    _require_super_admin(current_user)

    mem = db.query(TenantMembership).filter(
        TenantMembership.user_id == user_id,
        TenantMembership.tenant_id == tenant_id,
    ).first()
    if not mem:
        raise HTTPException(404, "Membership not found.")

    if role:
        mem.role = role
    if is_active is not None:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.is_active = is_active

    db.commit()
    return {"ok": True, "message": "Member updated."}


@router.delete("/admin/tenants/{tenant_id}/members/{user_id}")
def admin_remove_member(
    tenant_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a user from a tenant (super_admin only)."""
    _require_super_admin(current_user)

    mem = db.query(TenantMembership).filter(
        TenantMembership.user_id == user_id,
        TenantMembership.tenant_id == tenant_id,
    ).first()
    if not mem:
        raise HTTPException(404, "Membership not found.")
    if mem.role == "owner":
        raise HTTPException(400, "Cannot remove the tenant owner.")

    db.delete(mem)
    # Clear active_tenant_id if it was this tenant
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.active_tenant_id == tenant_id:
        user.active_tenant_id = None
    db.commit()
    return {"ok": True, "message": "Member removed."}


@router.put("/admin/tenants/{tenant_id}/members/{user_id}/reset-password")
def admin_reset_password(
    tenant_id: int,
    user_id: int,
    new_password: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reset a user's password (super_admin only)."""
    _require_super_admin(current_user)

    if len(new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found.")

    user.hashed_password = hash_password(new_password)
    db.commit()
    return {"ok": True, "message": f"Password reset for {user.email}."}


# ─── Tenant Admin: User Management ───────────────────────────

@router.post("/tenant/users")
def tenant_admin_create_user(
    name: str = "",
    email: str = "",
    password: str = "",
    role: str = "member",
    db: Session = Depends(get_db),
    current_tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """Create a new user in the current tenant (tenant admin/owner only)."""
    from app.services.usage_service import check_quota, METRIC_USERS
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "team_management")

    # Check role
    mem = db.query(TenantMembership).filter(
        TenantMembership.user_id == current_user.id,
        TenantMembership.tenant_id == current_tenant.id,
    ).first()
    if not mem or mem.role not in ("owner", "admin"):
        raise HTTPException(403, "Only tenant admins and owners can create users.")

    if not email or not password:
        raise HTTPException(400, "Email and password are required.")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")

    check_quota(db, current_tenant, METRIC_USERS)

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        em = db.query(TenantMembership).filter(
            TenantMembership.user_id == existing.id,
            TenantMembership.tenant_id == current_tenant.id,
        ).first()
        if em:
            raise HTTPException(400, "User is already a member of this tenant.")
        db.add(TenantMembership(user_id=existing.id, tenant_id=current_tenant.id, role=role))
        db.commit()
        return {"ok": True, "message": f"Added existing user {email} to tenant."}

    new_user = User(
        email=email,
        name=name or email.split("@")[0],
        hashed_password=hash_password(password),
        system_role="member",
        is_active=True,
        active_tenant_id=current_tenant.id,
    )
    db.add(new_user)
    db.flush()
    db.add(TenantMembership(user_id=new_user.id, tenant_id=current_tenant.id, role=role))
    db.commit()
    return {"ok": True, "user_id": new_user.id, "message": f"Created user {email}."}


@router.put("/tenant/members/{user_id}/reset-password")
def tenant_admin_reset_password(
    user_id: int,
    new_password: str = "",
    db: Session = Depends(get_db),
    current_tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """Reset a user's password (tenant admin/owner only)."""
    mem = db.query(TenantMembership).filter(
        TenantMembership.user_id == current_user.id,
        TenantMembership.tenant_id == current_tenant.id,
    ).first()
    if not mem or mem.role not in ("owner", "admin"):
        raise HTTPException(403, "Only tenant admins and owners can reset passwords.")

    if len(new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")

    target_mem = db.query(TenantMembership).filter(
        TenantMembership.user_id == user_id,
        TenantMembership.tenant_id == current_tenant.id,
    ).first()
    if not target_mem:
        raise HTTPException(404, "User is not a member of this tenant.")

    # Tenant admins cannot reset the owner's password — only the owner or super admin can
    if target_mem.role == "owner" and current_user.system_role != "super_admin":
        raise HTTPException(403, "Only the owner or system admin can reset the owner's password.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found.")

    user.hashed_password = hash_password(new_password)
    db.commit()
    return {"ok": True, "message": f"Password reset for {user.email}."}


@router.put("/tenant/members/{user_id}/toggle-active")
def tenant_admin_toggle_active(
    user_id: int,
    db: Session = Depends(get_db),
    current_tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """Activate/deactivate a user (tenant admin/owner only)."""
    mem = db.query(TenantMembership).filter(
        TenantMembership.user_id == current_user.id,
        TenantMembership.tenant_id == current_tenant.id,
    ).first()
    if not mem or mem.role not in ("owner", "admin"):
        raise HTTPException(403, "Only tenant admins and owners can toggle user status.")

    target_mem = db.query(TenantMembership).filter(
        TenantMembership.user_id == user_id,
        TenantMembership.tenant_id == current_tenant.id,
    ).first()
    if not target_mem:
        raise HTTPException(404, "User is not a member of this tenant.")
    if target_mem.role == "owner":
        raise HTTPException(400, "Cannot deactivate the tenant owner.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found.")

    user.is_active = not user.is_active
    db.commit()
    return {"ok": True, "is_active": user.is_active, "message": f"User {'activated' if user.is_active else 'deactivated'}."}


# ─── Data Export (Business+ feature) ─────────────────────────

@router.get("/tenant/export")
def export_tenant(
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Export all tenant data as JSON (Business+ feature)."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "data_export")
    from app.services.data_export import export_tenant_data
    return export_tenant_data(db, current_tenant.id)


@router.get("/tenant/export/projects/{project_id}")
def export_project(
    project_id: int,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Export a single project's data as JSON."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "data_export")
    from app.services.data_export import export_project_data
    data = export_project_data(db, current_tenant.id, project_id)
    if data is None:
        raise HTTPException(404, "Project not found.")
    return data


# ─── Audit Log (Enhanced) ────────────────────────────────────

@router.get("/tenant/audit-log")
def get_audit_log(
    page: int = 1,
    per_page: int = 50,
    entity_type: str = None,
    action: str = None,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)),
):
    """Paginated audit log with filters (owner/admin only)."""
    from app.models.activity_log import ActivityLog
    q = db.query(ActivityLog).filter(ActivityLog.tenant_id == current_tenant.id)
    if entity_type:
        q = q.filter(ActivityLog.entity_type == entity_type)
    if action:
        q = q.filter(ActivityLog.action == action)

    total = q.count()
    offset = (page - 1) * per_page
    entries = q.order_by(ActivityLog.created_at.desc()).offset(offset).limit(per_page).all()

    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
        "entries": [
            {
                "id": e.id,
                "user_id": e.user_id,
                "user_name": e.user_name,
                "project_id": e.project_id,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "action": e.action,
                "summary": e.summary,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }


# ─── GDPR Data Deletion ──────────────────────────────────────

@router.delete("/tenant/data")
def delete_tenant_data(
    confirm: str = "DELETE",
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    _user: User = Depends(require_tenant_role(MEMBER_ROLE_OWNER)),
):
    """Delete ALL tenant data (GDPR right to erasure). Owner only.

    This permanently deletes all projects, backlog items, releases, etc.
    The tenant itself and its memberships are preserved (use admin to delete tenant).
    Pass confirm=DELETE to proceed.
    """
    if confirm != "DELETE":
        raise HTTPException(400, "Pass confirm=DELETE to confirm data deletion.")

    tid = current_tenant.id
    deleted = {}

    # Delete in dependency order
    from app.models.release import ReleaseItem, Release
    from app.models.approval import ApprovalRequest, ApprovalStep
    from app.models.backlog_item import BacklogItem, backlog_dependencies
    from app.models.form_template import FormInstance, FormTemplate
    from app.models.kpi import KPI
    from app.models.milestone import Milestone
    from app.models.roadmap import Roadmap
    from app.models.stakeholder import Stakeholder
    from app.models.user_persona import UserPersona
    from app.models.project_test_account import ProjectTestAccount
    from app.models.project_vision import ProjectVision
    from app.models.github_board_config import GitHubBoardConfig
    from app.models.user_task import UserTask
    from app.models.notification import Notification
    from app.models.activity_log import ActivityLog

    deleted["release_items"] = db.query(ReleaseItem).filter(ReleaseItem.tenant_id == tid).delete()
    deleted["releases"] = db.query(Release).filter(Release.tenant_id == tid).delete()
    deleted["approval_steps"] = db.query(ApprovalStep).filter(ApprovalStep.tenant_id == tid).delete()
    deleted["approval_requests"] = db.query(ApprovalRequest).filter(ApprovalRequest.tenant_id == tid).delete()
    deleted["backlog_items"] = db.query(BacklogItem).filter(BacklogItem.tenant_id == tid).delete()
    deleted["form_instances"] = db.query(FormInstance).filter(FormInstance.tenant_id == tid).delete()
    deleted["form_templates"] = db.query(FormTemplate).filter(FormTemplate.tenant_id == tid).delete()
    deleted["kpis"] = db.query(KPI).filter(KPI.tenant_id == tid).delete()
    deleted["milestones"] = db.query(Milestone).filter(Milestone.tenant_id == tid).delete()
    deleted["roadmaps"] = db.query(Roadmap).filter(Roadmap.tenant_id == tid).delete()
    deleted["stakeholders"] = db.query(Stakeholder).filter(Stakeholder.tenant_id == tid).delete()
    deleted["personas"] = db.query(UserPersona).filter(UserPersona.tenant_id == tid).delete()
    deleted["test_accounts"] = db.query(ProjectTestAccount).filter(ProjectTestAccount.tenant_id == tid).delete()
    deleted["visions"] = db.query(ProjectVision).filter(ProjectVision.tenant_id == tid).delete()
    deleted["github_configs"] = db.query(GitHubBoardConfig).filter(GitHubBoardConfig.tenant_id == tid).delete()
    deleted["user_tasks"] = db.query(UserTask).filter(UserTask.tenant_id == tid).delete()
    deleted["notifications"] = db.query(Notification).filter(Notification.tenant_id == tid).delete()
    deleted["activity_logs"] = db.query(ActivityLog).filter(ActivityLog.tenant_id == tid).delete()
    deleted["projects"] = db.query(Project).filter(Project.tenant_id == tid).delete()

    db.commit()
    return {"ok": True, "deleted": deleted}


# ─── SSO (OIDC) — structure only, local ──────────────────────

@router.get("/auth/sso/providers")
def list_sso_providers(
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List available SSO providers (Business+ feature)."""
    from app.services.plan_enforcement import require_feature
    from app.services.sso_service import list_available_providers
    require_feature(current_tenant.plan, "sso_oidc")
    return {"providers": list_available_providers()}


@router.get("/auth/sso/{provider}/initiate")
def initiate_sso(
    provider: str,
    redirect_uri: str = "http://localhost:8000/api/auth/sso/callback",
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Initiate SSO login flow (Business+ feature).

    Returns the authorization URL to redirect the user to.
    Requires PMO_SSO_{PROVIDER}_CLIENT_ID and PMO_SSO_{PROVIDER}_CLIENT_SECRET env vars.
    """
    from app.services.plan_enforcement import require_feature
    from app.services.sso_service import get_authorization_url
    require_feature(current_tenant.plan, "sso_oidc")

    try:
        url = get_authorization_url(provider, redirect_uri)
        return {"authorization_url": url, "provider": provider}
    except ValueError as e:
        raise HTTPException(400, str(e))

