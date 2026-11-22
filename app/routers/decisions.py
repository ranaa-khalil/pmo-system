"""Decision records — R3: decisions of any call, one place, searchable, chained.

POST   /api/decisions                 create (title + decision required)
GET    /api/decisions                 list for the tenant, paginated newest first
                                      (?project_id= ?item_id= filters, ?q= searches
                                      across title/decision/rationale)
GET    /api/decisions/{id}            one record (tenant-gated)
PUT    /api/decisions/{id}            title/decision/rationale/alternatives editable —
                                      made_at/made_by are immutable (the schema drops them)
POST   /api/decisions/{id}/supersede  create the successor (chained_from_id lineage) and
                                      mark this one superseded
DELETE /api/decisions/{id}            house can_manage_project (projectless → tenant admin)

Every create/supersede appends a hash-linked artifact_chain entry
(entity_type="decision", action="created"/"superseded") via append_artifact
exactly like the reports router; the delete records "deleted" first so nothing
vanishes unrecorded. The chain is never bypassed.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.decision_record import SOURCES, DecisionRecord
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.permissions import can_manage_project, is_tenant_admin
from app.services.artifact_chain import append_artifact
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["decisions"])


class DecisionBody(BaseModel):
    """Create/supersede body — the new decision's fields."""

    title: str
    decision: str
    rationale: str | None = None
    alternatives: str | None = None
    project_id: int | None = None
    item_id: int | None = None
    approval_request_id: int | None = None
    source: str = "manual"


class DecisionUpdate(BaseModel):
    """Edit body — content only. made_at/made_by are immutable by shape."""

    title: str | None = None
    decision: str | None = None
    rationale: str | None = None
    alternatives: str | None = None


def _decision_row(d: DecisionRecord) -> dict:
    return {
        "id": d.id,
        "tenant_id": d.tenant_id,
        "project_id": d.project_id,
        "title": d.title,
        "decision": d.decision,
        "rationale": d.rationale,
        "alternatives": d.alternatives,
        "made_by": d.made_by,
        "made_at": d.made_at,
        "source": d.source,
        "item_id": d.item_id,
        "approval_request_id": d.approval_request_id,
        "chained_from_id": d.chained_from_id,
        "status": d.status,
    }


def _validate_links(db: Session, current_tenant: Tenant, req: DecisionBody) -> None:
    """Every link must resolve inside the tenant — no cross-tenant chains.

    Raises 404 on the first link that doesn't resolve; returns None when all do.
    """
    if req.project_id is not None:
        project = db.query(Project).filter(
            Project.id == req.project_id, Project.tenant_id == current_tenant.id
        ).first()
        if not project:
            raise HTTPException(404, "Project not found")

    if req.item_id is not None:
        item = db.query(BacklogItem).filter(BacklogItem.id == req.item_id).first()
        if not item:
            raise HTTPException(404, "Backlog item not found")
        ok = item.tenant_id == current_tenant.id
        if not ok and item.project_id:
            proj = db.query(Project).filter(Project.id == item.project_id).first()
            ok = proj is not None and proj.tenant_id == current_tenant.id
        if not ok:
            raise HTTPException(404, "Backlog item not found")

    if req.approval_request_id is not None:
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.id == req.approval_request_id
        ).first()
        if not request:
            raise HTTPException(404, "Approval request not found")
        ok = request.tenant_id == current_tenant.id
        if not ok:
            proj = db.query(Project).filter(Project.id == request.project_id).first()
            ok = proj is not None and proj.tenant_id == current_tenant.id
        if not ok:
            raise HTTPException(404, "Approval request not found")


def _check_source(req: DecisionBody) -> None:
    if req.source not in SOURCES:
        raise HTTPException(422, f"Source must be one of: {', '.join(SOURCES)}")


def _get_tenant_decision(db: Session, decision_id: int, current_tenant: Tenant) -> DecisionRecord:
    record = db.query(DecisionRecord).filter(
        DecisionRecord.id == decision_id,
        DecisionRecord.tenant_id == current_tenant.id,
    ).first()
    if not record:
        raise HTTPException(404, "Decision not found")
    return record


@router.post("/decisions", status_code=201)
def create_decision(
    req: DecisionBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Record a decision: any call, any source — the chain entry locks it in."""
    _check_source(req)
    if not req.title.strip() or not req.decision.strip():
        raise HTTPException(422, "title and decision are required")
    _validate_links(db, current_tenant, req)

    record = DecisionRecord(
        tenant_id=current_tenant.id,
        project_id=req.project_id,
        title=req.title.strip()[:255],
        decision=req.decision.strip(),
        rationale=req.rationale,
        alternatives=req.alternatives,
        made_by=current_user.id,
        # made_at: server_default now() — never set by the API
        source=req.source,
        item_id=req.item_id,
        approval_request_id=req.approval_request_id,
        status="active",
    )
    db.add(record)
    db.flush()
    db.refresh(record)  # loads id + made_at from the server default
    entry = append_artifact(
        db, current_tenant.id, "decision", record.id, "created",
        actor_id=current_user.id, actor_name=current_user.name,
        payload={"title": record.title, "source": record.source, "made_at": record.made_at},
        artifact_type="decision",
    )
    db.commit()  # append_artifact flushes but does not commit
    db.refresh(record)

    row = _decision_row(record)
    row["chain"] = {"seq": entry.seq, "hash": entry.hash}
    return row


@router.get("/decisions")
def list_decisions(
    project_id: int | None = None,
    item_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """One place: every decision for the tenant, paginated newest first.

    ?q= searches across title/decision/rationale; ?project_id= and ?item_id=
    chain the list to the work.
    """
    query = db.query(DecisionRecord).filter(DecisionRecord.tenant_id == current_tenant.id)
    if project_id is not None:
        query = query.filter(DecisionRecord.project_id == project_id)
    if item_id is not None:
        query = query.filter(DecisionRecord.item_id == item_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            DecisionRecord.title.ilike(like),
            DecisionRecord.decision.ilike(like),
            DecisionRecord.rationale.ilike(like),
        ))
    per_page = max(1, min(per_page, 200))
    total = query.count()
    offset = (max(1, page) - 1) * per_page
    rows = query.order_by(
        DecisionRecord.made_at.desc(), DecisionRecord.id.desc()
    ).offset(offset).limit(per_page).all()
    return {
        "page": max(1, page),
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
        "decisions": [_decision_row(r) for r in rows],
    }


@router.get("/decisions/{decision_id}")
def get_decision(
    decision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    record = _get_tenant_decision(db, decision_id, current_tenant)
    return _decision_row(record)


@router.put("/decisions/{decision_id}")
def update_decision(
    decision_id: int,
    req: DecisionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Edit the content — made_at/made_by are immutable (not in the schema)."""
    record = _get_tenant_decision(db, decision_id, current_tenant)
    made_at, made_by = record.made_at, record.made_by  # immutable — snapshot before edit
    for field in ("title", "decision", "rationale", "alternatives"):
        value = getattr(req, field)
        if value is not None:
            setattr(record, field, value.strip()[:255] if field == "title" else value)
    db.commit()
    db.refresh(record)
    row = _decision_row(record)
    assert row["made_at"] == made_at and row["made_by"] == made_by  # never editable
    return row


@router.post("/decisions/{decision_id}/supersede", status_code=201)
def supersede_decision(
    decision_id: int,
    req: DecisionBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Supersede: the successor carries chained_from_id; the old one is superseded.

    Both records get chain entries — the successor "created", the old "superseded".
    """
    _check_source(req)
    if not req.title.strip() or not req.decision.strip():
        raise HTTPException(422, "title and decision are required")
    old = _get_tenant_decision(db, decision_id, current_tenant)
    if old.status == "superseded":
        raise HTTPException(422, "This decision is already superseded")
    _validate_links(db, current_tenant, req)

    # The successor chains to the old record's work unless the body re-points it
    successor = DecisionRecord(
        tenant_id=current_tenant.id,
        project_id=req.project_id if req.project_id is not None else old.project_id,
        title=req.title.strip()[:255],
        decision=req.decision.strip(),
        rationale=req.rationale,
        alternatives=req.alternatives,
        made_by=current_user.id,
        # made_at: server_default now() — never set by the API
        source=req.source,
        item_id=req.item_id if req.item_id is not None else old.item_id,
        approval_request_id=(
            req.approval_request_id if req.approval_request_id is not None else old.approval_request_id
        ),
        chained_from_id=old.id,
        status="active",
    )
    old.status = "superseded"
    db.add(successor)
    db.flush()
    db.refresh(successor)  # loads id + made_at
    created_entry = append_artifact(
        db, current_tenant.id, "decision", successor.id, "created",
        actor_id=current_user.id, actor_name=current_user.name,
        payload={
            "title": successor.title, "source": successor.source,
            "supersedes": old.id, "made_at": successor.made_at,
        },
        artifact_type="decision",
    )
    superseded_entry = append_artifact(
        db, current_tenant.id, "decision", old.id, "superseded",
        actor_id=current_user.id, actor_name=current_user.name,
        payload={"superseded_by": successor.id, "title": successor.title},
        artifact_type="decision",
    )
    db.commit()  # append_artifact flushes but does not commit
    db.refresh(successor)
    db.refresh(old)

    row = _decision_row(successor)
    row["chain"] = {"seq": created_entry.seq, "hash": created_entry.hash}
    row["superseded_chain"] = {"seq": superseded_entry.seq, "hash": superseded_entry.hash}
    return row


@router.delete("/decisions/{decision_id}")
def delete_decision(
    decision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """House rule: can_manage_project (projectless decisions → tenant admin)."""
    record = _get_tenant_decision(db, decision_id, current_tenant)
    if record.project_id:
        project = db.query(Project).filter(Project.id == record.project_id).first()
        if project and not can_manage_project(current_user, project, db):
            raise HTTPException(403, "You don't have permission to manage this project's decisions")
    elif not is_tenant_admin(current_user, db):
        raise HTTPException(403, "Only tenant admins can delete projectless decisions")

    # The delete must not vanish: record it in the chain, then remove the row.
    append_artifact(
        db, current_tenant.id, "decision", record.id, "deleted",
        actor_id=current_user.id, actor_name=current_user.name,
        payload={"title": record.title},
        artifact_type="decision",
    )
    db.delete(record)
    db.commit()
    return {"deleted": decision_id}
