"""Release API router — V-cycle release management with full detail."""
from typing import List
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.backlog_item import BacklogItem, PHASES
from app.models.release import Release, ReleaseItem, RELEASE_STATUSES
from app.models.milestone import Milestone
from app.models.form_template import FormInstance
from app.models.approval import ApprovalRequest, ApprovalStep
from app.schemas.release import ReleaseCreate, ReleaseUpdate, ReleaseResponse

router = APIRouter(prefix="/api", tags=["releases"])

# V-cycle phases in order (maps release status to the V-cycle)
V_CYCLE = [
    ("Planning", "Requirements gathered, items selected", "brand"),
    ("In Progress", "Design + Development underway", "blue"),
    ("Testing", "System Integration Testing (SIT)", "amber"),
    ("UAT", "User Acceptance Testing", "violet"),
    ("Pre-Release", "Release notes, deployment prep", "orange"),
    ("Released", "Deployed to production", "emerald"),
    ("Post-Release", "Monitoring, hotfixes if needed", "teal"),
    ("Cancelled", "Release abandoned", "rose"),
]


@router.post("/projects/{project_id}/releases", response_model=ReleaseResponse, status_code=201)
def create_release(
    project_id: int,
    release: ReleaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new release for a project."""
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    db_release = Release(
        project_id=project_id,
        created_by=current_user.id,
        **release.model_dump(),
    )
    db.add(db_release)
    db.commit()
    db.refresh(db_release)
    return db_release


@router.get("/projects/{project_id}/releases", response_model=List[ReleaseResponse])
def list_releases(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all releases for a project."""
    return db.query(Release).filter(Release.project_id == project_id).order_by(Release.created_at.desc()).all()


@router.get("/releases/{release_id}", response_model=dict)
def get_release(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get release detail with linked backlog items, forms, approvals, milestone, and progress."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    # Backlog items
    items = []
    done_phases = ["Pre-Release", "Release", "Post-Release", "Retrospective"]
    for ri in release.items:
        bi = db.query(BacklogItem).filter(BacklogItem.id == ri.backlog_item_id).first()
        if bi:
            items.append({
                "id": bi.id, "title": bi.title, "description": bi.description,
                "current_phase": bi.current_phase, "status": bi.status,
                "priority": bi.priority, "kpi_id": bi.kpi_id,
                "is_done": bi.current_phase in done_phases,
            })

    total_items = len(items)
    completed_items = len([i for i in items if i["is_done"]])

    # Milestone
    milestone = None
    if release.milestone_id:
        ms = db.query(Milestone).filter(Milestone.id == release.milestone_id).first()
        if ms:
            milestone = {
                "id": ms.id, "title": ms.title,
                "target_date": str(ms.target_date) if ms.target_date else None,
                "status": ms.status,
            }

    # Forms (linked to this project)
    forms = []
    form_instances = db.query(FormInstance).filter(FormInstance.project_id == release.project_id).all()
    for fi in form_instances:
        forms.append({
            "id": fi.id, "template_id": fi.template_id,
            "status": fi.status, "submitted_by": fi.submitted_by,
        })

    # Approvals (for this project, type=release)
    approvals = []
    approval_requests = db.query(ApprovalRequest).filter(
        ApprovalRequest.project_id == release.project_id,
        ApprovalRequest.request_type == "release",
    ).all()
    for ar in approval_requests:
        steps = db.query(ApprovalStep).filter(ApprovalStep.approval_request_id == ar.id).order_by(ApprovalStep.step_order).all()
        current_step = None
        for s in steps:
            if s.status == "Pending":
                current_step = {"role_name": s.role_name, "step_order": s.step_order}
                break
        approvals.append({
            "id": ar.id, "title": ar.title, "status": ar.status,
            "total_steps": len(steps),
            "approved_steps": len([s for s in steps if s.status == "Approved"]),
            "current_step": current_step,
        })

    # V-cycle progress
    v_cycle_index = -1
    for i, (phase, _, _) in enumerate(V_CYCLE):
        if release.status == phase:
            v_cycle_index = i
            break
    v_cycle_progress = round((v_cycle_index / (len(V_CYCLE) - 2)) * 100) if v_cycle_index >= 0 and v_cycle_index < len(V_CYCLE) - 1 else 100

    # Phase actions — what the user can do next
    next_phase = None
    if v_cycle_index >= 0 and v_cycle_index < len(V_CYCLE) - 2:  # not Released or Cancelled
        next_phase = V_CYCLE[v_cycle_index + 1][0]

    return {
        "id": release.id,
        "project_id": release.project_id,
        "version": release.version,
        "name": release.name,
        "description": release.description,
        "status": release.status,
        "target_date": release.target_date,
        "release_date": release.release_date,
        "release_notes": release.release_notes,
        "milestone_id": release.milestone_id,
        "milestone": milestone,
        "created_by": release.created_by,
        "items": items,
        "total_items": total_items,
        "completed_items": completed_items,
        "progress_pct": round((completed_items / total_items * 100) if total_items > 0 else 0),
        "v_cycle_index": v_cycle_index,
        "v_cycle_progress": v_cycle_progress,
        "next_phase": next_phase,
        "forms": forms,
        "approvals": approvals,
        "v_cycle": [{"phase": p, "description": d, "color": c} for p, d, c in V_CYCLE],
    }


@router.put("/releases/{release_id}", response_model=ReleaseResponse)
def update_release(
    release_id: int,
    update: ReleaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a release."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    for field, val in update.model_dump(exclude_unset=True).items():
        setattr(release, field, val)
    db.commit()
    db.refresh(release)
    return release


@router.post("/releases/{release_id}/advance", response_model=dict)
def advance_phase(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Advance the release to the next V-cycle phase (sequential only)."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    if release.status == "Released":
        raise HTTPException(status_code=400, detail="Release is already in Released state")
    if release.status == "Cancelled":
        raise HTTPException(status_code=400, detail="Cannot advance a cancelled release")
    if release.status == "Post-Release":
        raise HTTPException(status_code=400, detail="Release is already in the final phase (Post-Release)")

    current_idx = -1
    for i, (phase, _, _) in enumerate(V_CYCLE):
        if release.status == phase:
            current_idx = i
            break
    if current_idx < 0:
        raise HTTPException(status_code=400, detail=f"Unknown status: {release.status}")

    next_phase = V_CYCLE[current_idx + 1][0]
    release.status = next_phase
    if next_phase == "Released":
        release.release_date = date.today().isoformat()
    db.commit()
    db.refresh(release)
    return {"id": release.id, "status": release.status, "message": f"Advanced to {next_phase}"}


@router.delete("/releases/{release_id}", status_code=204)
def delete_release(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a release."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    db.delete(release)
    db.commit()


@router.post("/releases/{release_id}/items/{backlog_item_id}", status_code=201)
def add_item_to_release(
    release_id: int,
    backlog_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Link a backlog item to a release."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    item = db.query(BacklogItem).filter(BacklogItem.id == backlog_item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")
    existing = db.query(ReleaseItem).filter(
        ReleaseItem.release_id == release_id,
        ReleaseItem.backlog_item_id == backlog_item_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Item already in this release")
    ri = ReleaseItem(release_id=release_id, backlog_item_id=backlog_item_id)
    db.add(ri)
    db.commit()
    return {"message": "Item added to release"}


@router.delete("/releases/{release_id}/items/{backlog_item_id}", status_code=204)
def remove_item_from_release(
    release_id: int,
    backlog_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a backlog item from a release."""
    ri = db.query(ReleaseItem).filter(
        ReleaseItem.release_id == release_id,
        ReleaseItem.backlog_item_id == backlog_item_id,
    ).first()
    if not ri:
        raise HTTPException(status_code=404, detail="Item not in this release")
    db.delete(ri)
    db.commit()


@router.post("/releases/{release_id}/generate-notes", response_model=dict)
def generate_release_notes(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-generate structured release notes from completed backlog items."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    items = []
    for ri in release.items:
        bi = db.query(BacklogItem).filter(BacklogItem.id == ri.backlog_item_id).first()
        if bi:
            items.append(bi)

    # Group by phase and priority
    done_phases = ["Pre-Release", "Release", "Post-Release", "Retrospective"]
    completed = [i for i in items if i.current_phase in done_phases]
    in_progress = [i for i in items if i.current_phase not in done_phases]

    # Categorize by priority
    critical = [i for i in completed if i.priority == "Critical"]
    high = [i for i in completed if i.priority == "High"]
    medium = [i for i in completed if i.priority == "Medium"]
    low = [i for i in completed if i.priority == "Low"]

    today = date.today().isoformat()
    notes_lines = [
        f"# Release {release.version} — {release.name}",
        f"**Date:** {release.release_date or today}",
        f"**Status:** {release.status}",
        f"**Milestone:** {release.milestone_id or 'Not linked'}",
        "",
        "---",
        "",
    ]

    if release.description:
        notes_lines.append("## 📋 Overview")
        notes_lines.append(release.description)
        notes_lines.append("")

    if critical:
        notes_lines.append("## 🔴 Critical Updates")
        for item in critical:
            notes_lines.append(f"- **{item.title}**")
            if item.description:
                notes_lines.append(f"  {item.description}")
        notes_lines.append("")

    if high:
        notes_lines.append("## 🟠 New Features & Improvements")
        for item in high:
            notes_lines.append(f"- **{item.title}**")
            if item.description:
                notes_lines.append(f"  {item.description}")
        notes_lines.append("")

    if medium:
        notes_lines.append("## 🟡 Enhancements")
        for item in medium:
            notes_lines.append(f"- {item.title}")
        notes_lines.append("")

    if low:
        notes_lines.append("## 🟢 Minor Changes")
        for item in low:
            notes_lines.append(f"- {item.title}")
        notes_lines.append("")

    if in_progress:
        notes_lines.append("## 🔄 In Progress (Carried Over)")
        for item in in_progress:
            notes_lines.append(f"- **{item.title}** — {item.current_phase} ({item.status})")
        notes_lines.append("")

    notes_lines.append("---")
    notes_lines.append(f"**Total items:** {len(items)}")
    notes_lines.append(f"**Completed:** {len(completed)} | **In Progress:** {len(in_progress)}")
    notes_lines.append(f"**Progress:** {round((len(completed) / len(items) * 100) if items else 0)}%")

    notes = "\n".join(notes_lines)
    release.release_notes = notes
    db.commit()

    return {"release_notes": notes, "total_items": len(items), "completed": len(completed)}
