"""Client portal API (P4) — read-only progress surface for client logins.

Two halves:
1. Portal side (unauthenticated login → scoped portal token):
   POST /api/portal/login            — contact_email + passcode → portal JWT
   GET  /api/portal/overview         — client's projects, progress, releases, milestones
2. Management side (PM/super admin, normal user JWT):
   POST /api/clients/{id}/portal     — enable portal + set/regenerate passcode
   DELETE /api/clients/{id}/portal   — disable portal

Security: portal tokens carry scope="portal" and are REJECTED by the user
API dependency (get_current_user). User tokens lack the scope and are
rejected by get_portal_client. Mutual exclusion by construction.
Passcodes are bcrypt-hashed (never stored or returned in plaintext).
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.release import Release
from app.models.roadmap import Roadmap
from app.models.tenant import Tenant
from app.models.user import User
from app.permissions import is_super_admin, is_tenant_admin_or_owner
from app.services.auth import (
    create_portal_token,
    decode_portal_token,
    hash_password,
    verify_password,
)
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api/portal", tags=["portal"])
mgmt_router = APIRouter(prefix="/api/clients", tags=["portal"])

bearer_scheme = HTTPBearer(auto_error=False)

# Phases that count as "done" for progress (same definition as dashboard.py)
DONE_PHASES = ["Pre-Release", "Release", "Post-Release", "Retrospective"]


def get_portal_client(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Client:
    """Validate a portal token and return the client it belongs to."""
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid portal session",
    )
    if credentials is None:
        raise cred_exc
    payload = decode_portal_token(credentials.credentials)
    if payload is None:
        raise cred_exc
    sub = payload.get("sub") or ""
    if not sub.startswith("client:"):
        raise cred_exc
    try:
        client_id = int(sub.split(":", 1)[1])
    except ValueError:
        raise cred_exc
    client = db.query(Client).filter(Client.id == client_id).first()
    # Portal must still be enabled and the client must still have a passcode
    if not client or not client.portal_enabled or not client.portal_passcode_hash:
        raise cred_exc
    return client


class PortalLoginRequest(BaseModel):
    email: EmailStr
    passcode: str


class PortalSetupRequest(BaseModel):
    passcode: str | None = None  # None → auto-generate


# ── Portal side ──────────────────────────────────────────────────────────────


@router.post("/login")
def portal_login(req: PortalLoginRequest, db: Session = Depends(get_db)):
    """Client contact logs in with email + passcode → scoped portal token."""
    client = db.query(Client).filter(Client.contact_email == req.email).first()
    if (
        not client
        or not client.portal_enabled
        or not client.portal_passcode_hash
        or not verify_password(req.passcode, client.portal_passcode_hash)
    ):
        # Uniform 401 — no enumeration of which clients have portals
        raise HTTPException(status_code=401, detail="Invalid email or passcode")
    token = create_portal_token(client.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "client": {"id": client.id, "name": client.name},
    }


@router.get("/overview")
def portal_overview(
    client: Client = Depends(get_portal_client),
    db: Session = Depends(get_db),
):
    """Read-only progress surface for the logged-in client.

    Shows ONLY this client's projects: status, backlog progress,
    releases (version/status/target date/notes), and roadmap milestones.
    No financials, no internal team data, no other clients.
    """
    projects = db.query(Project).filter(Project.client_id == client.id).all()

    project_data = []
    all_releases = []
    all_milestones = []
    for p in projects:
        items = db.query(BacklogItem).filter(BacklogItem.project_id == p.id).all()
        done = len([i for i in items if i.current_phase in DONE_PHASES])
        total = len(items)
        progress_pct = round((done / total * 100) if total else 0)

        releases = (
            db.query(Release)
            .filter(Release.project_id == p.id)
            .order_by(Release.created_at.desc())
            .all()
        )
        for r in releases:
            all_releases.append({
                "id": r.id,
                "project_id": p.id,
                "project_name": p.name,
                "version": r.version,
                "name": r.name,
                "status": r.status,
                "target_date": r.target_date,
                "release_date": r.release_date,
            })

        roadmap_ids = [
            row[0]
            for row in db.query(Roadmap.id).filter(Roadmap.project_id == p.id).all()
        ]
        if roadmap_ids:
            for ms in db.query(Milestone).filter(Milestone.roadmap_id.in_(roadmap_ids)).all():
                all_milestones.append({
                    "id": ms.id,
                    "project_id": p.id,
                    "project_name": p.name,
                    "title": ms.title,
                    "target_date": str(ms.target_date) if ms.target_date else None,
                    "status": ms.status,
                })

        project_data.append({
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "description": p.description,
            "backlog_total": total,
            "backlog_done": done,
            "progress_pct": progress_pct,
            "releases_count": len(releases),
        })

    all_milestones.sort(key=lambda m: m.get("target_date") or "9999")

    return {
        "client": {"id": client.id, "name": client.name},
        "projects": project_data,
        "releases": all_releases,
        "milestones": all_milestones,
    }


# ── Management side (PM / tenant admin / super admin) ────────────────────────


def _require_portal_manager(current_user: User, db: Session, client: Client) -> None:
    if is_super_admin(current_user):
        return
    if is_tenant_admin_or_owner(current_user, db):
        return
    if current_user.system_role == "account_manager" and client.account_manager_id == current_user.id:
        return
    raise HTTPException(status_code=403, detail="You don't have permission to manage this client's portal")


@mgmt_router.post("/{client_id}/portal")
def setup_portal(
    client_id: int,
    req: PortalSetupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Enable the portal for a client and set (or regenerate) the passcode.

    Returns the plaintext passcode ONCE — only the bcrypt hash is stored.
    """
    client = db.query(Client).filter(Client.id == client_id, Client.tenant_id == current_tenant.id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not client.contact_email:
        raise HTTPException(status_code=400, detail="Client needs a contact email before enabling the portal")
    _require_portal_manager(current_user, db, client)

    passcode = req.passcode if req.passcode else secrets.token_urlsafe(9)
    if len(passcode) < 8:
        raise HTTPException(status_code=422, detail="Passcode must be at least 8 characters")
    client.portal_passcode_hash = hash_password(passcode)
    client.portal_enabled = True
    db.commit()
    db.refresh(client)
    return {
        "client_id": client.id,
        "portal_enabled": True,
        "passcode": passcode,  # shown once — never stored in plaintext
    }


@mgmt_router.delete("/{client_id}/portal", status_code=200)
def disable_portal(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Disable the portal for a client (revokes portal access immediately)."""
    client = db.query(Client).filter(Client.id == client_id, Client.tenant_id == current_tenant.id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_portal_manager(current_user, db, client)
    client.portal_enabled = False
    client.portal_passcode_hash = None
    db.commit()
    return {"client_id": client.id, "portal_enabled": False}


@mgmt_router.get("/{client_id}/portal")
def portal_status(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Check whether a client's portal is enabled (never returns the passcode)."""
    client = db.query(Client).filter(Client.id == client_id, Client.tenant_id == current_tenant.id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"client_id": client.id, "portal_enabled": bool(client.portal_enabled)}
