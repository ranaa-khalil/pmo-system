"""Public share links — read-only dashboard/project views.

Authenticated: create/list/revoke links (expiry + optional password).
Public: view the scoped aggregate (no login). Read-only by design — the
payload never includes members, settings, or anything beyond the scope.
"""
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.activity_log import ActivityLog
from app.models.backlog_item import BacklogItem
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.release import Release
from app.models.share_link import SHARE_SCOPES, ShareLink
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.share_link import ShareLinkCreate
from app.services.auth import hash_password, verify_password
from app.services.notifications import log_activity
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["share"])
public_router = APIRouter(prefix="/api/share", tags=["share"])


def _link_url(token: str) -> str:
    return f"/share/{token}"


def _link_payload(link: ShareLink, target_name: str | None = None) -> dict:
    return {
        "id": link.id,
        "token": link.token,
        "scope": link.scope,
        "project_id": link.project_id,
        "target_name": target_name,
        "has_password": bool(link.password_hash),
        "expires_at": link.expires_at,
        "revoked": link.revoked,
        "view_count": link.view_count,
        "url": _link_url(link.token),
    }


@router.post("/share-links", status_code=201)
def create_share_link(
    body: ShareLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a public read-only view link."""
    tid = current_tenant.id
    if body.scope not in SHARE_SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of: {SHARE_SCOPES}")
    if not 1 <= body.expires_in_days <= 90:
        raise HTTPException(status_code=400, detail="expires_in_days must be between 1 and 90")
    if body.scope == "project":
        if not body.project_id:
            raise HTTPException(status_code=400, detail="project_id is required for project scope")
        if not db.query(Project).filter(Project.id == body.project_id, Project.tenant_id == tid).first():
            raise HTTPException(status_code=404, detail="Project not found")

    link = ShareLink(
        tenant_id=tid,
        token=secrets.token_urlsafe(32),
        scope=body.scope,
        project_id=body.project_id if body.scope == "project" else None,
        password_hash=hash_password(body.password) if body.password else None,
        expires_at=(datetime.utcnow() + timedelta(days=body.expires_in_days)).isoformat(),
        created_by=current_user.id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    target = ""
    if body.scope == "project":
        target = db.query(Project).filter(Project.id == body.project_id).first().name
    log_activity(db, current_user.id, current_user.name, body.project_id,
                 "share", link.id, "created",
                 f"Created {body.scope} share link" + (f" for {target}" if target else ""))
    return _link_payload(link)


@router.get("/share-links")
def list_share_links(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List the tenant's share links with target names."""
    links = db.query(ShareLink).filter(ShareLink.tenant_id == current_tenant.id).order_by(
        ShareLink.created_at.desc()
    ).all()
    result = []
    for link in links:
        target_name = None
        if link.project_id:
            project = db.query(Project).filter(Project.id == link.project_id).first()
            target_name = project.name if project else None
        result.append(_link_payload(link, target_name))
    return result


@router.delete("/share-links/{link_id}")
def revoke_share_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Revoke a share link (views then 410)."""
    link = db.query(ShareLink).filter(
        ShareLink.id == link_id, ShareLink.tenant_id == current_tenant.id
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    link.revoked = True
    db.commit()
    return {"detail": "Link revoked"}


# ---- Public (no auth) ----

def _load_valid_link(db: Session, token: str) -> ShareLink:
    link = db.query(ShareLink).filter(ShareLink.token == token).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    if link.revoked:
        raise HTTPException(status_code=410, detail="This link has been revoked")
    if link.expires_at:
        try:
            expires = datetime.fromisoformat(link.expires_at)
        except ValueError:
            raise HTTPException(status_code=410, detail="This link is not valid")
        if datetime.utcnow() > expires:
            raise HTTPException(status_code=410, detail="This link has expired")
    return link


def _view_payload(db: Session, link: ShareLink) -> dict:
    """The scoped read-only aggregate (never members/settings)."""
    tenant = db.query(Tenant).filter(Tenant.id == link.tenant_id).first()
    generated_at = datetime.utcnow().isoformat()
    if link.scope == "project":
        project = db.query(Project).filter(Project.id == link.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        items = db.query(BacklogItem).filter(BacklogItem.project_id == project.id).all()
        by_status = {}
        for it in items:
            by_status[it.status] = by_status.get(it.status, 0) + 1
        from app.models.roadmap import Roadmap

        roadmap_ids = [
            r.id for r in db.query(Roadmap).filter(Roadmap.project_id == project.id).all()
        ]
        milestones = db.query(Milestone).filter(
            Milestone.roadmap_id.in_(roadmap_ids)
        ).all() if roadmap_ids else []
        releases = db.query(Release).filter(Release.project_id == project.id).order_by(
            Release.created_at.desc()
        ).limit(5).all()
        return {
            "scope": "project",
            "tenant_name": tenant.name if tenant else None,
            "generated_at": generated_at,
            "project": {
                "name": project.name,
                "status": project.status,
                "description": project.description,
            },
            "backlog": {
                "total": len(items),
                "by_status": by_status,
                "progress": round(len([i for i in items if i.status == "Done"]) / len(items) * 100) if items else 0,
            },
            "milestones": [
                {"title": m.title, "target_date": str(m.target_date) if m.target_date else None, "status": m.status}
                for m in milestones
            ][:6],
            "releases": [
                {"version": r.version, "name": r.name, "status": r.status}
                for r in releases
            ],
        }
    # dashboard scope — tenant-wide aggregate
    projects = db.query(Project).filter(Project.tenant_id == link.tenant_id).all()
    project_data = []
    for p in projects:
        items = db.query(BacklogItem).filter(BacklogItem.project_id == p.id).all()
        done = len([i for i in items if i.status == "Done"])
        project_data.append({
            "name": p.name,
            "status": p.status,
            "total_items": len(items),
            "done_items": done,
            "progress": round(done / len(items) * 100) if items else 0,
        })
    releases = db.query(Release).filter(Release.tenant_id == link.tenant_id).order_by(
        Release.created_at.desc()
    ).limit(5).all()
    activity = db.query(ActivityLog).filter(ActivityLog.tenant_id == link.tenant_id).order_by(
        ActivityLog.created_at.desc()
    ).limit(10).all()
    return {
        "scope": "dashboard",
        "tenant_name": tenant.name if tenant else None,
        "generated_at": generated_at,
        "projects": project_data,
        "releases": [
            {"version": r.version, "name": r.name, "status": r.status}
            for r in releases
        ],
        "activity": [
            {"summary": a.summary, "action": a.action, "created_at": a.created_at}
            for a in activity
        ],
    }


@public_router.get("/{token}")
def view_share(token: str, db: Session = Depends(get_db)):
    """Public read-only view. If the link has a password, returns requires_password."""
    link = _load_valid_link(db, token)
    if link.password_hash:
        return {
            "requires_password": True,
            "scope": link.scope,
            "expires_at": link.expires_at,
        }
    link.view_count = (link.view_count or 0) + 1
    link.last_viewed_at = datetime.utcnow().isoformat()
    db.commit()
    return _view_payload(db, link)


@public_router.post("/{token}")
def unlock_share(token: str, body: dict, db: Session = Depends(get_db)):
    """View a password-protected share link."""
    link = _load_valid_link(db, token)
    if not link.password_hash:
        return _view_payload(db, link)
    password = (body or {}).get("password") or ""
    if not verify_password(password, link.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")
    link.view_count = (link.view_count or 0) + 1
    link.last_viewed_at = datetime.utcnow().isoformat()
    db.commit()
    return _view_payload(db, link)
