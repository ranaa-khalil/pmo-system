"""RAID API — one register, four kinds (Risk | Assumption | Issue | Dependency).

GET  /api/projects/{id}/risks        list the register (optional ?kind= filter)
POST /api/projects/{id}/risks        create (PM or super admin only, kind-validated)
PUT  /api/risks/{risk_id}            update status/severity/probability/mitigation + kind fields
POST /api/risks/{risk_id}/escalate   escalate along the chain (assumption→risk, risk→issue,
                                     dependency→issue) — creates the target with
                                     escalated_from_id lineage and closes/flags the source

Score is computed from severity × probability on every read — never stored.
Statuses are validated per kind (KIND_STATUSES); issues are terminal.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import Project
from app.models.risk import ESCALATION_TARGET, KIND_STATUSES, RAID_KINDS, Risk
from app.models.tenant import TenantMembership
from app.models.user import User

router = APIRouter(prefix="/api", tags=["risks"])


class RiskCreate(BaseModel):
    title: str
    kind: str = "Risk"
    description: str | None = None
    severity: str = "Medium"
    probability: str = "Medium"
    release_id: int | None = None
    validation_plan: str | None = None
    needed_by: str | None = None
    external_owner: str | None = None


class RiskUpdate(BaseModel):
    status: str | None = None
    severity: str | None = None
    probability: str | None = None
    mitigation: str | None = None
    validation_plan: str | None = None
    resolution: str | None = None
    needed_by: str | None = None
    external_owner: str | None = None


def _risk_row(risk: Risk) -> dict:
    return {
        "id": risk.id,
        "project_id": risk.project_id,
        "title": risk.title,
        "description": risk.description,
        "mitigation": risk.mitigation,
        "severity": risk.severity,
        "probability": risk.probability,
        "status": risk.status,
        "score": risk.score,
        "source": risk.source,
        "owner_id": risk.owner_id,
        "kind": risk.kind,
        "validation_plan": risk.validation_plan,
        "resolution": risk.resolution,
        "needed_by": str(risk.needed_by) if risk.needed_by else None,
        "external_owner": risk.external_owner,
        "escalated_from_id": risk.escalated_from_id,
        "created_at": risk.created_at.isoformat() if risk.created_at else None,
    }


def _load_project(db: Session, project_id: int, user: User) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == user.id, TenantMembership.tenant_id == project.tenant_id,
    ).first()
    if not membership and user.system_role != "super_admin":
        raise HTTPException(403, "You don't have access to this project")
    return project


def _load_risk_with_permission(db: Session, risk_id: int, user: User) -> Risk:
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if not risk:
        raise HTTPException(404, "RAID entry not found")
    project = db.query(Project).filter(Project.id == risk.project_id).first()
    if project and project.project_manager_id != user.id and user.system_role != "super_admin":
        raise HTTPException(403, "Only the project manager can modify RAID entries")
    return risk


@router.get("/projects/{project_id}/risks")
def list_risks(project_id: int, kind: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _load_project(db, project_id, current_user)
    query = db.query(Risk).filter(
        Risk.tenant_id == project.tenant_id, Risk.project_id == project.id,
    )
    if kind:
        if kind not in RAID_KINDS:
            raise HTTPException(422, f"Unknown kind: {kind}")
        query = query.filter(Risk.kind == kind)
    rows = query.order_by(Risk.id.desc()).all()
    return [_risk_row(r) for r in rows]


@router.post("/projects/{project_id}/risks")
def create_risk(project_id: int, req: RiskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _load_project(db, project_id, current_user)
    if project.project_manager_id != current_user.id and current_user.system_role != "super_admin":
        raise HTTPException(403, "Only the project manager can create RAID entries")
    if req.kind not in RAID_KINDS:
        raise HTTPException(422, f"Kind must be one of: {', '.join(RAID_KINDS)}")
    needed_by = None
    if req.needed_by:
        try:
            needed_by = datetime.strptime(req.needed_by, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(422, "needed_by must be an ISO date (YYYY-MM-DD)")
    risk = Risk(
        tenant_id=project.tenant_id, project_id=project.id,
        title=req.title[:255], description=req.description,
        severity=req.severity, probability=req.probability,
        kind=req.kind, status="Open",
        validation_plan=req.validation_plan,
        needed_by=needed_by,
        external_owner=req.external_owner,
        owner_id=current_user.id, source="manual",
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    return _risk_row(risk)


@router.put("/risks/{risk_id}")
def update_risk(risk_id: int, req: RiskUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    risk = _load_risk_with_permission(db, risk_id, current_user)
    if req.status is not None:
        allowed = KIND_STATUSES.get(risk.kind, ["Open", "Mitigating", "Closed"])
        if req.status not in allowed:
            raise HTTPException(422, f"Status '{req.status}' is not valid for a {risk.kind} (allowed: {', '.join(allowed)})")
    needed_by = None
    if req.needed_by is not None:
        if req.needed_by:
            try:
                needed_by = datetime.strptime(req.needed_by, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(422, "needed_by must be an ISO date (YYYY-MM-DD)")
    for field in ("status", "severity", "probability", "mitigation", "validation_plan", "resolution", "external_owner"):
        value = getattr(req, field)
        if value is not None:
            setattr(risk, field, value)
    if req.needed_by is not None:
        risk.needed_by = needed_by
    db.commit()
    db.refresh(risk)
    return _risk_row(risk)


# ── Escalation chain ─────────────────────────────────────────

_ESCALATION_PREFIX = {
    "Assumption": "Invalidated assumption: ",
    "Risk": "Materialized risk: ",
    "Dependency": "Blocked dependency: ",
}


@router.post("/risks/{risk_id}/escalate")
def escalate_risk(risk_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    src = _load_risk_with_permission(db, risk_id, current_user)
    target_kind = ESCALATION_TARGET.get(src.kind)
    if not target_kind:
        raise HTTPException(422, "Issues are terminal — they cannot escalate further")
    now = datetime.now(UTC).replace(tzinfo=None)
    new = Risk(
        tenant_id=src.tenant_id, project_id=src.project_id,
        kind=target_kind,
        title=(_ESCALATION_PREFIX[src.kind] + src.title)[:255],
        description=src.description,
        severity=src.severity, probability=src.probability,
        status="Open",
        owner_id=src.owner_id or current_user.id,
        source="escalation",
        escalated_from_id=src.id,
        date_raised=now,
    )
    # Flag the source per the chain: invalidated assumption, closed risk, blocked dependency
    if src.kind == "Assumption":
        src.status = "Invalidated"
    elif src.kind == "Risk":
        src.status = "Closed"
    elif src.kind == "Dependency":
        src.status = "Blocked"
    db.add(new)
    db.commit()
    db.refresh(new)
    return _risk_row(new)
