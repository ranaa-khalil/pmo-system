"""Project status reports — locked on delivery.

Generate a snapshot of project health (progress, releases, risks, milestones)
and "send" it: each send appends a hash-linked artifact_chain entry
(artifact_type="report"), so delivered reports are tamper-evident and
listable forever.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.artifact_chain import ArtifactChain
from app.models.backlog_item import BacklogItem
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.release import Release
from app.models.risk import Risk
from app.models.roadmap import Roadmap
from app.models.tenant import Tenant
from app.models.user import User
from app.services.artifact_chain import append_artifact
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["reports"])


def _build_report(db: Session, project: Project, user: User) -> dict:
    """Read-only snapshot of project health — no guesses, counts only."""
    items = db.query(BacklogItem).filter(BacklogItem.project_id == project.id).all()
    by_phase = {}
    by_status = {}
    for it in items:
        by_phase[it.current_phase] = by_phase.get(it.current_phase, 0) + 1
        by_status[it.status] = by_status.get(it.status, 0) + 1
    done = by_status.get("Done", 0)

    releases = db.query(Release).filter(Release.project_id == project.id).order_by(
        Release.created_at.desc()
    ).limit(5).all()
    risks = db.query(Risk).filter(
        Risk.project_id == project.id, Risk.status != "Closed"
    ).order_by(Risk.severity.desc()).limit(8).all()

    roadmap_ids = [r.id for r in db.query(Roadmap).filter(Roadmap.project_id == project.id).all()]
    milestones = db.query(Milestone).filter(
        Milestone.roadmap_id.in_(roadmap_ids)
    ).order_by(Milestone.target_date).all() if roadmap_ids else []

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "status": project.status,
        },
        "generated_at": datetime.utcnow().isoformat(),
        "generated_by": user.name,
        "backlog": {
            "total": len(items),
            "done": done,
            "progress": round(done / len(items) * 100) if items else 0,
            "by_phase": by_phase,
            "by_status": by_status,
        },
        "releases": [
            {"version": r.version, "name": r.name, "status": r.status}
            for r in releases
        ],
        "open_risks": [
            {"title": r.title, "severity": r.severity, "status": r.status}
            for r in risks
        ],
        "milestones": [
            {"title": m.title, "target_date": str(m.target_date) if m.target_date else None, "status": m.status}
            for m in milestones
        ][:6],
    }


@router.post("/projects/{project_id}/reports/send", status_code=201)
def send_status_report(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Generate a status report snapshot and lock it: one artifact_chain entry per send."""
    project = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    report = _build_report(db, project, current_user)
    entry = append_artifact(
        db, current_tenant.id, "report", project.id, "sent",
        actor_id=current_user.id, actor_name=current_user.name,
        payload={"report": report},
        artifact_type="report",
    )
    db.commit()  # append_artifact flushes but does not commit
    db.refresh(entry)
    return {
        "report": report,
        "entry": {
            "id": entry.id,
            "seq": entry.seq,
            "hash": entry.hash,
            "action": entry.action,
            "artifact_type": entry.artifact_type,
            "created_at": str(entry.created_at),
        },
    }


@router.get("/projects/{project_id}/reports")
def list_status_reports(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delivered reports for one project — newest first, from the immutable chain."""
    project = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    entries = db.query(ArtifactChain).filter(
        ArtifactChain.entity_type == "report",
        ArtifactChain.entity_id == project_id,
        ArtifactChain.tenant_id == current_tenant.id,
    ).order_by(ArtifactChain.seq.desc()).limit(20).all()
    return [
        {
            "id": e.id,
            "seq": e.seq,
            "hash": e.hash,
            "actor_name": e.actor_name,
            "created_at": str(e.created_at),
            "report": (e.payload or {}).get("report"),
        }
        for e in entries
    ]
