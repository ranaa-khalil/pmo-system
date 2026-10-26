"""Risks API — register CRUD scoped to a project.

GET  /api/projects/{id}/risks        list the register (tenant + PM visibility)
POST /api/projects/{id}/risks        create (PM or super admin only)
PUT  /api/risks/{risk_id}            update status/severity/probability/mitigation

Score is computed from severity × probability on every read — never stored.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import Project
from app.models.risk import Risk
from app.models.tenant import TenantMembership
from app.models.user import User

router = APIRouter(prefix="/api", tags=["risks"])


class RiskCreate(BaseModel):
    title: str
    description: str | None = None
    severity: str = "Medium"
    probability: str = "Medium"
    release_id: int | None = None


class RiskUpdate(BaseModel):
    status: str | None = None
    severity: str | None = None
    probability: str | None = None
    mitigation: str | None = None


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


@router.get("/projects/{project_id}/risks")
def list_risks(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _load_project(db, project_id, current_user)
    rows = db.query(Risk).filter(
        Risk.tenant_id == project.tenant_id, Risk.project_id == project.id,
    ).order_by(Risk.id.desc()).all()
    return [_risk_row(r) for r in rows]


@router.post("/projects/{project_id}/risks")
def create_risk(project_id: int, req: RiskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _load_project(db, project_id, current_user)
    if project.project_manager_id != current_user.id and current_user.system_role != "super_admin":
        raise HTTPException(403, "Only the project manager can create risks")
    risk = Risk(
        tenant_id=project.tenant_id, project_id=project.id,
        title=req.title[:255], description=req.description,
        severity=req.severity, probability=req.probability,
        status="Open", owner_id=current_user.id, source="manual",
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    return _risk_row(risk)


@router.put("/risks/{risk_id}")
def update_risk(risk_id: int, req: RiskUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if not risk:
        raise HTTPException(404, "Risk not found")
    project = db.query(Project).filter(Project.id == risk.project_id).first()
    if project and project.project_manager_id != current_user.id and current_user.system_role != "super_admin":
        raise HTTPException(403, "Only the project manager can update risks")
    for field in ("status", "severity", "probability", "mitigation"):
        value = getattr(req, field)
        if value is not None:
            setattr(risk, field, value)
    db.commit()
    db.refresh(risk)
    return _risk_row(risk)
