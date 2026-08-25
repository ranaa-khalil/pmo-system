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

# ── Automatic approval routing ──────────────────────────────────────────────
# When a release advances from phase X → phase X+1, an approval request is
# auto-created and routed to the RACI role that GATE-KEEPS phase X.
# The release cannot advance until that role approves.
#
# Mapping: current_phase → (gate_keeper_role, gate_description)
PHASE_GATE_ROLES = {
    "Planning":     ("Product Owner",   "Approve requirements are complete and ready for development"),
    "In Progress":  ("Tech Lead",       "Approve code completion and readiness for testing"),
    "Testing":      ("QA Lead",         "Approve SIT results and readiness for UAT"),
    "UAT":          ("Product Owner",   "Approve UAT passed and readiness for release"),
    "Pre-Release":  ("Release Manager", "Approve deployment checklist and go-live"),
    "Released":     ("Release Manager", "Confirm deployment success and begin monitoring"),
}


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

    # Approvals (for this project, type=release, linked to THIS release)
    approvals = []
    approval_requests = db.query(ApprovalRequest).filter(
        ApprovalRequest.project_id == release.project_id,
        ApprovalRequest.request_type == "release",
        ApprovalRequest.release_id == release_id,
    ).all()
    pending_approval = None
    for ar in approval_requests:
        steps = db.query(ApprovalStep).filter(ApprovalStep.request_id == ar.id).order_by(ApprovalStep.step_order).all()
        current_step = None
        for s in steps:
            if s.status == "Pending":
                current_step = {"role_name": s.role_name, "step_order": s.step_order, "id": s.id}
                break
        approval_data = {
            "id": ar.id, "title": ar.title, "status": ar.status,
            "target_phase": ar.target_phase,
            "total_steps": len(steps),
            "approved_steps": len([s for s in steps if s.status == "Approved"]),
            "current_step": current_step,
        }
        approvals.append(approval_data)
        if ar.status == "Pending" and not pending_approval:
            pending_approval = approval_data

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
        "pending_approval": pending_approval,
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
    """Request advancement to the next V-cycle phase.

    Instead of immediately advancing, this creates an approval request routed
    to the RACI role that gate-keeps the CURRENT phase. The release advances
    only when that role approves (see approve_step in approvals.py).

    If an approval is already pending for this release, returns its status.
    If the approval was already approved, advances the release immediately and
    creates the next phase's approval.
    """
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

    # Check if there's already an approval for this release + target phase
    existing = db.query(ApprovalRequest).filter(
        ApprovalRequest.release_id == release_id,
        ApprovalRequest.target_phase == next_phase,
    ).first()

    if existing:
        if existing.status == "Pending":
            # Find the pending step + role
            step = db.query(ApprovalStep).filter(
                ApprovalStep.request_id == existing.id,
                ApprovalStep.status == "Pending",
            ).first()
            role = step.role_name if step else "Unknown"
            return {
                "id": release.id,
                "status": release.status,
                "approval_status": "pending",
                "approval_id": existing.id,
                "pending_role": role,
                "target_phase": next_phase,
                "message": f"Approval still pending from {role}. Request #{existing.id}.",
            }
        elif existing.status == "Approved":
            # Approval granted — advance the release now
            release.status = next_phase
            if next_phase == "Released":
                release.release_date = date.today().isoformat()
            db.commit()
            db.refresh(release)

            # Auto-create the next phase's approval (if there is one)
            next_approval = _create_phase_approval(db, release, current_user)
            result = {
                "id": release.id,
                "status": release.status,
                "approval_status": "approved",
                "target_phase": next_phase,
                "message": f"Advanced to {next_phase}",
            }
            if next_approval:
                result["next_approval_id"] = next_approval["id"]
                result["next_pending_role"] = next_approval["role"]
            return result
        elif existing.status == "Rejected":
            return {
                "id": release.id,
                "status": release.status,
                "approval_status": "rejected",
                "target_phase": next_phase,
                "message": f"Advancement to {next_phase} was rejected. See request #{existing.id}.",
            }

    # No existing approval — create one for the current phase's gate-keeper
    gate_info = PHASE_GATE_ROLES.get(release.status)
    if not gate_info:
        # No gate for this phase — advance directly
        release.status = next_phase
        if next_phase == "Released":
            release.release_date = date.today().isoformat()
        db.commit()
        db.refresh(release)
        return {"id": release.id, "status": release.status, "message": f"Advanced to {next_phase}"}

    gate_role, gate_desc = gate_info
    approval = ApprovalRequest(
        project_id=release.project_id,
        title=f"Release {release.version}: {release.status} → {next_phase}",
        description=gate_desc,
        request_type="release",
        requested_by=current_user.id,
        release_id=release_id,
        target_phase=next_phase,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    step = ApprovalStep(
        request_id=approval.id,
        step_order=1,
        role_name=gate_role,
    )
    db.add(step)
    db.commit()

    return {
        "id": release.id,
        "status": release.status,
        "approval_status": "created",
        "approval_id": approval.id,
        "pending_role": gate_role,
        "target_phase": next_phase,
        "message": f"Approval request #{approval.id} created for {gate_role}.",
    }


def _create_phase_approval(db: Session, release: Release, current_user: User):
    """Auto-create an approval request for the release's current phase gate-keeper.
    Returns {'id': approval_id, 'role': role_name} or None if no gate for this phase."""
    gate_info = PHASE_GATE_ROLES.get(release.status)
    if not gate_info:
        return None

    # Find the next phase
    current_idx = -1
    for i, (phase, _, _) in enumerate(V_CYCLE):
        if release.status == phase:
            current_idx = i
            break
    if current_idx < 0 or current_idx >= len(V_CYCLE) - 2:
        return None
    next_phase = V_CYCLE[current_idx + 1][0]

    gate_role, gate_desc = gate_info
    approval = ApprovalRequest(
        project_id=release.project_id,
        title=f"Release {release.version}: {release.status} → {next_phase}",
        description=gate_desc,
        request_type="release",
        requested_by=current_user.id,
        release_id=release.id,
        target_phase=next_phase,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    step = ApprovalStep(
        request_id=approval.id,
        step_order=1,
        role_name=gate_role,
    )
    db.add(step)
    db.commit()

    return {"id": approval.id, "role": gate_role}


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


@router.get("/projects/{project_id}/releases/next-version")
def get_next_version(
    project_id: int,
    bump: str = "minor",  # "major", "minor", or "patch"
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Suggest the next SemVer version for a project based on existing releases.

    Rules (from Versioning & Release Cadence v1.2):
    - MAJOR: breaking changes / new platform (1.x → 2.0.0)
    - MINOR: new features, monthly release train (1.0.0 → 1.1.0)
    - PATCH: hotfixes, bug fixes (1.0.0 → 1.0.1)

    If project has version_prefix (e.g. "1.0"), the first release is 1.0.0.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    releases = db.query(Release).filter(Release.project_id == project_id).all()

    if not releases:
        # First release — use version_prefix if set, otherwise 1.0.0
        if project.version_prefix:
            parts = project.version_prefix.split(".")
            major = int(parts[0]) if len(parts) > 0 else 1
            minor = int(parts[1]) if len(parts) > 1 else 0
            return {"version": f"{major}.{minor}.0", "bump": "initial", "previous": None}

        return {"version": "1.0.0", "bump": "initial", "previous": None}

    # Find the highest existing version
    def parse_version(v):
        try:
            parts = v.split(".")
            return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, int(parts[2]) if len(parts) > 2 else 0)
        except (ValueError, IndexError):
            return (0, 0, 0)

    latest = max(releases, key=lambda r: parse_version(r.version))
    major, minor, patch = parse_version(latest.version)

    if bump == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump == "patch":
        patch += 1
    else:  # minor (default)
        minor += 1
        patch = 0

    return {"version": f"{major}.{minor}.{patch}", "bump": bump, "previous": latest.version}


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
