"""Client engagements — R4: the contract wrapper around one client's projects.

POST   /api/engagements            create (name + client_id required; the client must
                                   be a THIS-tenant client — 400 otherwise, the kpi_id
                                   tenancy pattern)
GET    /api/engagements            list for the tenant, paginated newest first
                                   (?client_id= ?status= filters)
GET    /api/engagements/{id}       one engagement (tenant-gated) + the projects rollup:
                                   the tenant's projects for this client (count + list)
PUT    /api/engagements/{id}       name/status/dates/contract/notes/lead editable —
                                   client_id is immutable (the schema drops it)
DELETE /api/engagements/{id}       house can_manage_client (the client-level branch of
                                   the can_manage_project rule)

Create/delete append hash-linked artifact_chain entries
(entity_type="engagement") via append_artifact exactly like the reports
router; the delete records "deleted" first so nothing vanishes unrecorded.
The chain is never bypassed.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.client import Client
from app.models.engagement import STATUSES, Engagement
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.permissions import can_manage_client, is_tenant_admin
from app.services.artifact_chain import append_artifact
from app.services.scope import tenant_scoped
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["engagements"])


class EngagementBody(BaseModel):
    """Create body — name + client_id required; the rest optional."""

    name: str
    client_id: int
    status: str = "active"
    start_date: date | None = None
    end_date: date | None = None
    contract_value: str | None = None
    pmo_lead_id: int | None = None
    notes: str | None = None


class EngagementUpdate(BaseModel):
    """Edit body — content only. client_id is immutable by shape."""

    name: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    contract_value: str | None = None
    pmo_lead_id: int | None = None
    notes: str | None = None


def _engagement_row(e: Engagement) -> dict:
    return {
        "id": e.id,
        "tenant_id": e.tenant_id,
        "client_id": e.client_id,
        "name": e.name,
        "status": e.status,
        "start_date": e.start_date,
        "end_date": e.end_date,
        "contract_value": e.contract_value,
        "pmo_lead_id": e.pmo_lead_id,
        "notes": e.notes,
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }


def _check_status(status: str) -> None:
    if status not in STATUSES:
        raise HTTPException(422, f"Status must be one of: {', '.join(STATUSES)}")


def _validate_client(db: Session, current_tenant: Tenant, client_id: int) -> Client:
    """The client must be a THIS-tenant client — no cross-tenant contracts.

    The kpi_id tenancy pattern (Slice 9 QA fix): the raw body would otherwise
    write an engagement under another tenant's client.
    """
    client = tenant_scoped(db, Client, current_tenant.id).filter(
        Client.id == client_id
    ).first()
    if not client:
        raise HTTPException(400, "Client not found in this tenant")
    return client


def _validate_lead(db: Session, current_tenant: Tenant, lead_id: int) -> None:
    """The PMO lead must be a member of THIS tenant."""
    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == lead_id, TenantMembership.tenant_id == current_tenant.id
    ).first()
    if not membership:
        raise HTTPException(400, "PMO lead not found in this tenant")


def _get_tenant_engagement(db: Session, engagement_id: int, current_tenant: Tenant) -> Engagement:
    engagement = tenant_scoped(db, Engagement, current_tenant.id).filter(
        Engagement.id == engagement_id
    ).first()
    if not engagement:
        raise HTTPException(404, "Engagement not found")
    return engagement


def _projects_rollup(db: Session, current_tenant: Tenant, engagement: Engagement) -> dict:
    """The engagement → its projects direction: the tenant's projects for this client.

    Tenant-filtered on purpose — a project belonging to another tenant never
    appears here even if it shares the client_id.
    """
    projects = (
        tenant_scoped(db, Project, current_tenant.id)
        .filter(Project.client_id == engagement.client_id)
        .order_by(Project.created_at.desc(), Project.id.desc())
        .all()
    )
    return {
        "count": len(projects),
        "items": [{"id": p.id, "name": p.name, "status": p.status} for p in projects],
    }


@router.post("/engagements", status_code=201)
def create_engagement(
    req: EngagementBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Open an engagement: the contract wrapper around a client's projects."""
    if not req.name.strip():
        raise HTTPException(422, "name is required")
    _check_status(req.status)
    _validate_client(db, current_tenant, req.client_id)
    if req.pmo_lead_id is not None:
        _validate_lead(db, current_tenant, req.pmo_lead_id)

    engagement = Engagement(
        tenant_id=current_tenant.id,
        client_id=req.client_id,
        name=req.name.strip()[:255],
        status=req.status,
        start_date=req.start_date,
        end_date=req.end_date,
        contract_value=req.contract_value,
        pmo_lead_id=req.pmo_lead_id,
        notes=req.notes,
    )
    db.add(engagement)
    db.flush()
    db.refresh(engagement)  # loads id + created_at from the server default
    entry = append_artifact(
        db, current_tenant.id, "engagement", engagement.id, "created",
        actor_id=current_user.id, actor_name=current_user.name,
        payload={"name": engagement.name, "client_id": engagement.client_id, "status": engagement.status},
        artifact_type="engagement",
    )
    db.commit()  # append_artifact flushes but does not commit
    db.refresh(engagement)

    row = _engagement_row(engagement)
    row["chain"] = {"seq": entry.seq, "hash": entry.hash}
    return row


@router.get("/engagements")
def list_engagements(
    client_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Every engagement for the tenant, paginated newest first.

    ?client_id= scopes the list to one client; ?status= filters the lifecycle.
    """
    query = tenant_scoped(db, Engagement, current_tenant.id)
    if client_id is not None:
        query = query.filter(Engagement.client_id == client_id)
    if status:
        query = query.filter(Engagement.status == status)
    per_page = max(1, min(per_page, 200))
    total = query.count()
    offset = (max(1, page) - 1) * per_page
    rows = query.order_by(
        Engagement.created_at.desc(), Engagement.id.desc()
    ).offset(offset).limit(per_page).all()
    return {
        "page": max(1, page),
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
        "engagements": [_engagement_row(r) for r in rows],
    }


@router.get("/engagements/{engagement_id}")
def get_engagement(
    engagement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """One engagement + the projects rollup (the engagement → its projects direction)."""
    engagement = _get_tenant_engagement(db, engagement_id, current_tenant)
    row = _engagement_row(engagement)
    row["projects"] = _projects_rollup(db, current_tenant, engagement)
    return row


@router.put("/engagements/{engagement_id}")
def update_engagement(
    engagement_id: int,
    req: EngagementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Edit the engagement — client_id is immutable (not in the schema)."""
    engagement = _get_tenant_engagement(db, engagement_id, current_tenant)
    if req.status is not None:
        _check_status(req.status)
    if req.pmo_lead_id is not None:
        _validate_lead(db, current_tenant, req.pmo_lead_id)
    client_id = engagement.client_id  # immutable — snapshot before edit
    for field in ("name", "status", "start_date", "end_date", "contract_value", "pmo_lead_id", "notes"):
        value = getattr(req, field)
        if value is not None:
            setattr(engagement, field, value.strip()[:255] if field == "name" else value)
    db.commit()
    db.refresh(engagement)
    row = _engagement_row(engagement)
    assert row["client_id"] == client_id  # never editable
    return row


@router.delete("/engagements/{engagement_id}")
def delete_engagement(
    engagement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """House rule: can_manage_client (the client-level branch of can_manage_project)."""
    engagement = _get_tenant_engagement(db, engagement_id, current_tenant)
    client = db.query(Client).filter(Client.id == engagement.client_id).first()
    if client:
        if not can_manage_client(current_user, client, db):
            raise HTTPException(403, "You don't have permission to manage this client's engagements")
    elif not is_tenant_admin(current_user, db):
        raise HTTPException(403, "Only tenant admins can delete engagements")

    # The delete must not vanish: record it in the chain, then remove the row.
    append_artifact(
        db, current_tenant.id, "engagement", engagement.id, "deleted",
        actor_id=current_user.id, actor_name=current_user.name,
        payload={"name": engagement.name, "client_id": engagement.client_id},
        artifact_type="engagement",
    )
    db.delete(engagement)
    db.commit()
    return {"deleted": engagement_id}
