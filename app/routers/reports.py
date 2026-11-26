"""Project status reports — locked on delivery.

Generate a snapshot of project health (progress, releases, risks, milestones)
and "send" it: each send appends a hash-linked artifact_chain entry
(artifact_type="report"), so delivered reports are tamper-evident and
listable forever. R1: the send path also dispatches to explicit recipients
(the PM + stakeholders with an email) — the chain entry stays the audit row.

Rethink MVP (AI & Copilot): the send path is ALSO the Draft Desk's send door —
the one send path. Drafts (brief.generate_report, per audience, editable
inline) arrive as {audience, markdown} and are emailed as RENDERED MARKDOWN
per audience — never json.dumps output. A snapshot send (no draft) emails the
deterministic snapshot rendered as markdown. POST /projects/{id}/reports/draft
generates a Draft Desk draft; generation degrades to the deterministic
snapshot rendered as markdown when the LLM is down.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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
from app.models.stakeholder import Stakeholder
from app.models.tenant import Tenant
from app.models.user import User
from app.services.artifact_chain import append_artifact
from app.services.email import send_email
from app.services.scope import tenant_scoped
from app.services.settings_service import get_ai_config
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


class ReportSendRequest(BaseModel):
    """Draft Desk send payload (all optional — a bare send stays valid).

    When `markdown` is present the send carries an edited Draft Desk draft:
    it is emailed as rendered markdown per audience. `report_id` links the
    send back to the persisted draft (AiInteraction kind=report).
    """
    audience: str | None = None
    markdown: str | None = None
    report_id: int | None = None


@router.post("/projects/{project_id}/reports/draft")
def draft_status_report(
    project_id: int,
    req: ReportSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Generate a Draft Desk draft for ONE audience — editable before send.

    brief.generate_report is the LLM narrative over the same grounded data
    spine as the digest; when the LLM is down, unconfigured or over quota the
    draft degrades to the deterministic snapshot rendered as markdown
    (degraded=true) — the Draft Desk never blocks on the LLM.
    """
    from app.services import brief as brief_service

    project = tenant_scoped(db, Project, current_tenant.id).filter(
        Project.id == project_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    audience = req.audience or "exec_weekly"
    if audience not in brief_service.AUDIENCE_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown audience: {audience}. Known: {sorted(brief_service.AUDIENCE_PROFILES)}",
        )

    tenant_config = get_ai_config(db, current_tenant.id)
    fallback_markdown = brief_service.render_snapshot_markdown(
        _build_report(db, project, current_user)
    )
    draft = brief_service.draft_report(
        db, current_tenant, project, audience,
        user=current_user, tenant_config=tenant_config,
        fallback_markdown=fallback_markdown,
    )
    return {
        "audience": draft["audience"],
        "markdown": draft["markdown"],
        "sections": draft["sections"],
        "data_hash": draft["data_hash"],
        "report_id": draft["report_id"],
        "degraded": draft.get("degraded", False),
    }


@router.post("/projects/{project_id}/reports/send", status_code=201)
def send_status_report(
    project_id: int,
    req: ReportSendRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Generate a status report snapshot and lock it: one artifact_chain entry per send.

    THE ONE send path (the Draft Desk sends here too): with an edited draft
    the email body is the draft's rendered markdown (per audience); without
    one it is the deterministic snapshot rendered as markdown — never
    json.dumps output."""
    from app.services import brief as brief_service

    project = tenant_scoped(db, Project, current_tenant.id).filter(
        Project.id == project_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    payload = req or ReportSendRequest()
    draft_audience = payload.audience if payload.audience in brief_service.AUDIENCE_PROFILES else None
    draft_markdown = (payload.markdown or "").strip() or None

    report = _build_report(db, project, current_user)
    entry = append_artifact(
        db, current_tenant.id, "report", project.id, "sent",
        actor_id=current_user.id, actor_name=current_user.name,
        payload={
            "report": report,
            **({"draft": {"audience": draft_audience, "markdown": draft_markdown,
                          "report_id": payload.report_id}} if draft_markdown else {}),
        },
        artifact_type="report",
    )
    db.commit()  # append_artifact flushes but does not commit
    db.refresh(entry)

    # The email body is RENDERED MARKDOWN per audience — never json.dumps.
    if draft_markdown:
        body = draft_markdown
        subject = (
            f"[PMO] {brief_service.AUDIENCE_PROFILES[draft_audience]['label']} — {project.name}"
            if draft_audience else f"[PMO] Status report — {project.name}"
        )
    else:
        body = brief_service.render_snapshot_markdown(report)
        subject = f"[PMO] Status report — {project.name}"
    html = f"<pre style=\"font-family:inherit;white-space:pre-wrap\">{body}</pre>"

    # R1: report send gains recipients + dispatch (the artifact chain entry
    # above stays the tamper-evident audit row — dispatch never bypasses it).
    recipients: list[dict] = []
    if project.project_manager_id:
        pm = db.query(User).filter(User.id == project.project_manager_id).first()
        if pm and pm.email:
            recipients.append({"name": pm.name, "email": pm.email, "role": "pm"})
    for st in tenant_scoped(db, Stakeholder, current_tenant.id).filter(
        Stakeholder.project_id == project.id,
    ).all():
        if st.email:
            recipients.append({"name": st.name, "email": st.email, "role": st.role_name})
    dispatched = []
    for r in recipients:
        sent = send_email(
            db=db, tenant_id=current_tenant.id, to_email=r["email"],
            subject=subject, body=body, html=html,
        )
        dispatched.append({"email": r["email"], "sent": bool(sent)})

    return {
        "report": report,
        "audience": draft_audience,
        "markdown": draft_markdown or body,
        "degraded": False,
        "recipients": recipients,
        "dispatched": dispatched,
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
    project = tenant_scoped(db, Project, current_tenant.id).filter(
        Project.id == project_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    entries = tenant_scoped(db, ArtifactChain, current_tenant.id).filter(
        ArtifactChain.entity_type == "report",
        ArtifactChain.entity_id == project_id,
    ).order_by(ArtifactChain.seq.desc()).limit(20).all()
    return [
        {
            "id": e.id,
            "seq": e.seq,
            "hash": e.hash,
            "actor_name": e.actor_name,
            "created_at": str(e.created_at),
            "report": (e.payload or {}).get("report"),
            "draft": (e.payload or {}).get("draft"),
        }
        for e in entries
    ]
