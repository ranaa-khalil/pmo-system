"""Release API router — V-cycle release management with full detail."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.form_template import FormInstance, FormTemplate
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.release import Release, ReleaseItem
from app.models.role import Role
from app.models.user import User
from app.schemas.release import ReleaseCreate, ReleaseResponse, ReleaseUpdate
from app.services.notifications import log_activity

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
]

# Cancelled is a terminal status, not a phase in the progress bar
CANCELLED = "Cancelled"

# ── Automatic approval routing ──────────────────────────────────────────────
# When a release advances from phase X → phase X+1, an approval request is
# auto-created and routed to the RACI role that GATE-KEEPS phase X.
# The release cannot advance until that role approves.
#
# Mapping: current_phase → (gate_keeper_role, gate_description, checklist_items)
PHASE_GATE_ROLES = {
    "Planning":     ("Product Owner",   "Approve requirements are complete and ready for development",
                     ["Requirements reviewed and signed off",
                      "Backlog items selected for this release",
                      "Scope and priority agreed with stakeholders"]),
    "In Progress":  ("Tech Lead",       "Approve code completion and readiness for testing",
                     ["All features developed and code-reviewed",
                      "Unit tests passing",
                      "Technical debt logged and accepted",
                      "Branch merged to release branch"]),
    "Testing":      ("QA Lead",         "Approve SIT results and readiness for UAT",
                     ["System Integration Testing complete",
                      "All critical defects resolved",
                      "Regression tests passing",
                      "Test report generated"]),
    "UAT":          ("Product Manager", "Approve UAT passed and readiness for release",
                     ["UAT scenarios executed by business users",
                      "All must-fix defects resolved",
                      "Business sign-off obtained",
                      "No critical/severe open defects"]),
    "Pre-Release":  ("DevOps Lead",     "Approve deployment checklist and go-live",
                     ["Release notes generated and reviewed",
                      "Deployment runbook ready",
                      "Rollback plan prepared",
                      "DB migrations tested in staging",
                      "Monitoring and alerts configured"]),
    "Released":     ("DevOps Lead",     "Confirm deployment success and begin monitoring",
                     ["Deployment to production successful",
                      "Smoke tests passed in production",
                      "Stakeholders notified",
                      "Post-release monitoring active"]),
}


def _compute_phase_gates(release, items, v_cycle_index):
    """Compute phase gate checklist status based on actual release data.

    Each checklist item is evaluated against the real state of the release
    and its linked backlog items. Returns a list of gates with checklist
    items marked as checked or unchecked.
    """

    # Item stats
    total_items = len(items)
    done_items = len([i for i in items if i.get("is_done")])
    has_items = total_items > 0
    has_release_notes = bool(release.release_notes)

    # Check how many items are past each phase
    items_past_testing = len([i for i in items if i.get("current_phase") in ("Ready for UAT", "UAT", "Pre-Release", "Release", "Post-Release", "Retrospective")])
    items_in_or_past_testing = len([i for i in items if i.get("current_phase") in ("Testing", "Ready for UAT", "UAT", "Pre-Release", "Release", "Post-Release", "Retrospective")])
    items_past_development = len([i for i in items if i.get("current_phase") in ("Testing", "Ready for UAT", "UAT", "Pre-Release", "Release", "Post-Release", "Retrospective")])

    # Phase index helpers
    release_phases = [p for p, _, _ in V_CYCLE]
    current_idx = v_cycle_index

    def phase_reached(phase_name):
        """True if the release has passed this gate (moved beyond this phase)."""
        idx = release_phases.index(phase_name) if phase_name in release_phases else -1
        return current_idx > idx

    gates = []
    for phase, (role, desc, checklist) in PHASE_GATE_ROLES.items():
        gate_reached = phase_reached(phase)

        # Compute checked status for each checklist item
        checked_items = []
        for item_text in checklist:
            checked = _is_checklist_item_satisfied(
                item_text, phase, gate_reached, has_items, total_items,
                done_items, items_past_testing, items_in_or_past_testing,
                items_past_development, has_release_notes, release
            )
            checked_items.append({"text": item_text, "checked": checked})

        gates.append({
            "phase": phase,
            "role": role,
            "description": desc,
            "checklist": checked_items,
            "reached": gate_reached,
        })
    return gates


def _is_checklist_item_satisfied(item_text, phase, gate_reached, has_items,
                                  total_items, done_items, items_past_testing,
                                  items_in_or_past_testing, items_past_development,
                                  has_release_notes, release):
    """Determine if a specific checklist item is satisfied based on release data."""
    text = item_text.lower()

    # If the gate has been reached (release passed this phase), all items are checked
    if gate_reached:
        return True

    # Otherwise, check specific conditions based on the item text
    # Planning gate
    if "backlog items selected" in text:
        return has_items
    if "requirements reviewed" in text:
        return has_items and total_items > 0
    if "scope and priority" in text:
        return has_items

    # In Progress gate
    if "all features developed" in text:
        return total_items > 0 and items_past_development == total_items
    if "unit tests passing" in text:
        return total_items > 0 and items_past_development == total_items
    if "technical debt logged" in text:
        return total_items > 0 and items_past_development >= total_items * 0.5
    if "branch merged" in text:
        return total_items > 0 and items_past_development == total_items

    # Testing gate
    if "integration testing" in text or "sit" in text:
        return total_items > 0 and items_in_or_past_testing == total_items
    if "critical defects resolved" in text:
        return total_items > 0 and items_in_or_past_testing >= total_items * 0.5
    if "regression tests" in text:
        return total_items > 0 and items_in_or_past_testing == total_items
    if "test report" in text:
        return total_items > 0 and items_in_or_past_testing == total_items

    # UAT gate
    if "uat scenarios" in text:
        return phase_reached(release, "UAT")
    if "must-fix defects" in text:
        return phase_reached(release, "UAT")
    if "business sign-off" in text:
        return phase_reached(release, "UAT")
    if "no critical" in text:
        return phase_reached(release, "UAT")

    # Pre-Release gate
    if "release notes" in text:
        return has_release_notes
    if "deployment runbook" in text:
        return phase_reached(release, "Pre-Release")
    if "rollback plan" in text:
        return phase_reached(release, "Pre-Release")
    if "db migrations" in text:
        return phase_reached(release, "Pre-Release")
    if "monitoring and alerts" in text:
        return phase_reached(release, "Pre-Release")

    # Released gate
    if "deployment to production" in text:
        return phase_reached(release, "Released")
    if "smoke tests" in text:
        return phase_reached(release, "Released")
    if "stakeholders notified" in text:
        return phase_reached(release, "Released")
    if "post-release monitoring" in text:
        return phase_reached(release, "Released")

    return False


def phase_reached(release, phase_name):
    """Check if the release has passed the given phase (moved beyond it)."""
    release_phases = [p for p, _, _ in V_CYCLE]
    current_idx = -1
    for i, (p, _, _) in enumerate(V_CYCLE):
        if release.status == p:
            current_idx = i
            break
    target_idx = release_phases.index(phase_name) if phase_name in release_phases else -1
    return current_idx > target_idx


def _sync_release_items_to_phase(db: Session, release: Release, phase: str):
    """When a release advances, update all linked backlog items to reflect
    the release-level phase (UAT, Pre-Release, Release, Post-Release, Retrospective).

    Also auto-generate the appropriate form for the new phase.
    """
    from app.models.backlog_item import BacklogItem
    from app.models.release import ReleaseItem

    items = db.query(BacklogItem).join(
        ReleaseItem, ReleaseItem.backlog_item_id == BacklogItem.id
    ).filter(ReleaseItem.release_id == release.id).all()

    new_status = "Done" if phase in ("Release", "Post-Release", "Retrospective") else None

    for item in items:
        item.current_phase = phase
        if new_status:
            item.status = new_status

    db.commit()

    # Note: Sign-offs are handled by the approval system (PHASE_GATE_ROLES),
    # not by forms. Each phase gate auto-creates an approval request for the
    # accountable RACI role. No manual form creation needed.


# Mapping: release phase → (form_type, form_name)
PHASE_FORM_MAP = {
    "UAT": ("uat_signoff", "UAT Sign-off Form"),
    "Pre-Release": ("deployment_checklist", "Deployment Checklist"),
    "Post-Release": ("retrospective", "Retrospective Form"),
}


def _auto_generate_form_for_phase(db: Session, release: Release, phase: str):
    """Auto-create a form instance when a release enters a phase that requires a form."""
    from app.models.form_template import FormInstance, FormTemplate

    form_info = PHASE_FORM_MAP.get(phase)
    if not form_info:
        return

    form_type, form_name = form_info

    # Check if a form of this type already exists for this release's project
    template = db.query(FormTemplate).filter(FormTemplate.form_type == form_type).first()
    if not template:
        # Create the template if it doesn't exist
        template = _get_or_create_form_template(db, form_type, form_name)
        if not template:
            return

    # Check if an instance already exists for this project + template
    existing = db.query(FormInstance).filter(
        FormInstance.template_id == template.id,
        FormInstance.project_id == release.project_id,
    ).first()
    if existing:
        return  # Already exists, don't duplicate

    # Create the form instance
    fi = FormInstance(
        template_id=template.id,
        project_id=release.project_id,
        status="Draft",
        created_by=release.created_by,
        data={},
    )
    db.add(fi)
    db.commit()
    print(f"  📝 Auto-generated form: {form_name} (phase: {phase})")


def _get_or_create_form_template(db: Session, form_type: str, form_name: str):
    """Get or create a form template for the given type."""
    from app.models.form_template import FormTemplate

    # Check existing
    existing = db.query(FormTemplate).filter(FormTemplate.form_type == form_type).first()
    if existing:
        return existing

    # Define field schemas for each form type
    SCHEMAS = {
        "uat_signoff": [
            {"name": "tester_name", "label": "Tester Name", "type": "text"},
            {"name": "test_cases_run", "label": "Test Cases Run", "type": "number"},
            {"name": "test_cases_passed", "label": "Test Cases Passed", "type": "number"},
            {"name": "defects_found", "label": "Defects Found", "type": "number"},
            {"name": "signoff_decision", "label": "Sign-off Decision", "type": "select", "options": ["Approved", "Rejected", "Conditional"]},
            {"name": "comments", "label": "Comments", "type": "textarea"},
        ],
        "deployment_checklist": [
            {"name": "code_review_complete", "label": "Code review complete", "type": "boolean"},
            {"name": "tests_passing", "label": "All tests passing", "type": "boolean"},
            {"name": "docs_updated", "label": "Documentation updated", "type": "boolean"},
            {"name": "security_scan", "label": "Security scan passed", "type": "boolean"},
            {"name": "stakeholder_signoff", "label": "Stakeholder sign-off received", "type": "boolean"},
            {"name": "db_migrations", "label": "DB migrations applied", "type": "boolean"},
            {"name": "rollback_plan", "label": "Rollback plan ready", "type": "boolean"},
        ],
        "retrospective": [
            {"name": "what_went_well", "label": "What went well", "type": "textarea"},
            {"name": "what_didnt", "label": "What didn't go well", "type": "textarea"},
            {"name": "improvements", "label": "Improvements for next release", "type": "textarea"},
            {"name": "action_items", "label": "Action items", "type": "textarea"},
        ],
    }

    schema = SCHEMAS.get(form_type, [])
    template = FormTemplate(
        name=form_name,
        form_type=form_type,
        description=f"Auto-generated for {form_type.replace('_', ' ')}",
        field_schema=schema,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


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

    log_activity(db, current_user.id, current_user.name, project_id,
                 "release", db_release.id, "created",
                 f"Created release {db_release.version} — {db_release.name}")

    return db_release


@router.get("/projects/{project_id}/releases", response_model=list[ReleaseResponse])
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
        # Get template name and form_type
        template = db.query(FormTemplate).filter(FormTemplate.id == fi.template_id).first()
        forms.append({
            "id": fi.id, "template_id": fi.template_id,
            "status": fi.status, "created_by": fi.created_by,
            "name": template.name if template else f"Form #{fi.id}",
            "form_type": template.form_type if template else "",
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
        approver_name = None
        decided_at = None
        for s in steps:
            if s.status == "Pending":
                current_step = {"role_name": s.role_name, "step_order": s.step_order, "id": s.id}
            # Show approver name for both approved and pending steps
            if s.approver_id:
                approver_user = db.query(User).filter(User.id == s.approver_id).first()
                approver_name = approver_user.name if approver_user else s.role_name
                if s.status == "Approved":
                    decided_at = str(s.decided_at) if s.decided_at else None
        approval_data = {
            "id": ar.id, "title": ar.title, "status": ar.status,
            "target_phase": ar.target_phase,
            "total_steps": len(steps),
            "approved_steps": len([s for s in steps if s.status == "Approved"]),
            "current_step": current_step,
            "approver_name": approver_name,
            "decided_at": decided_at,
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
    v_cycle_progress = round((v_cycle_index / (len(V_CYCLE) - 1)) * 100) if v_cycle_index >= 0 else 0

    # Phase actions — what the user can do next
    next_phase = None
    if v_cycle_index >= 0 and v_cycle_index < len(V_CYCLE) - 1:  # not at final phase
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
        "phase_gates": _compute_phase_gates(release, items, v_cycle_index),
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
            _sync_release_items_to_phase(db, release, next_phase)
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
        _sync_release_items_to_phase(db, release, next_phase)
        db.commit()
        db.refresh(release)
        return {"id": release.id, "status": release.status, "message": f"Advanced to {next_phase}"}

    gate_role, gate_desc, gate_checklist = gate_info
    approval = ApprovalRequest(
        project_id=release.project_id,
        title=f"Release {release.version}: {release.status} → {next_phase}",
        description=gate_desc + "\n\nChecklist:\n" + "\n".join(f"☐ {item}" for item in gate_checklist),
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
    Returns {'id': approval_id, 'role': role_name} or None if no gate for this phase.

    The approval step is auto-assigned to the user who holds the gate-keeper
    role on this project (via RoleAssignment). If no user has the role,
    the step stays unassigned (role_name is set so it can be claimed later).
    """
    gate_info = PHASE_GATE_ROLES.get(release.status)
    if not gate_info:
        return None

    # Find the next phase
    current_idx = -1
    for i, (phase, _, _) in enumerate(V_CYCLE):
        if release.status == phase:
            current_idx = i
            break
    if current_idx < 0 or current_idx >= len(V_CYCLE) - 1:
        return None
    next_phase = V_CYCLE[current_idx + 1][0]

    gate_role, gate_desc, gate_checklist = gate_info

    # Find the user assigned to this role on this project
    from app.models.role import Role
    from app.models.role_assignment import RoleAssignment

    approver_id = None
    role = db.query(Role).filter(Role.name == gate_role).first()
    if role:
        assignment = db.query(RoleAssignment).filter(
            RoleAssignment.role_id == role.id,
            RoleAssignment.project_id == release.project_id,
        ).first()
        if assignment:
            approver_id = assignment.user_id

    approval = ApprovalRequest(
        project_id=release.project_id,
        title=f"Release {release.version}: {release.status} → {next_phase}",
        description=gate_desc + "\n\nChecklist:\n" + "\n".join(f"☐ {item}" for item in gate_checklist),
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
        approver_id=approver_id,  # Auto-assigned to the user with this role
    )
    db.add(step)
    db.commit()

    return {"id": approval.id, "role": gate_role, "approver_id": approver_id}


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


def _build_release_notes(release, project, items, milestone, prev_tag, db):
    """Build release notes matching Release_Notes_Template_v1.1.docx exactly."""
    from datetime import date

    done_phases = ["Pre-Release", "Release", "Post-Release", "Retrospective"]
    completed = [i for i in items if i.current_phase in done_phases]
    in_progress = [i for i in items if i.current_phase not in done_phases]

    # Determine release type from version
    ver_parts = release.version.lstrip("v").split(".")
    release_type = "Minor / Feature"
    if len(ver_parts) >= 3:
        try:
            patch = int(ver_parts[2])
            minor = int(ver_parts[1])
            major = int(ver_parts[0])
            if patch > 0:
                release_type = "Patch / Hotfix"
            elif minor == 0 and major > 0:
                release_type = "Major / Breaking"
        except (ValueError, IndexError):
            pass

    # Categorize items
    new_features = [i for i in completed if i.item_type and i.item_type.lower() in ("feature", "story", "user story")]
    enhancements = [i for i in completed if i.item_type and i.item_type.lower() in ("enhancement", "improvement", "task")]
    bug_fixes = [i for i in completed if i.item_type and i.item_type.lower() in ("bug", "defect", "fix")]
    # If no item_type set, use priority as fallback categorization
    if not new_features and not enhancements and not bug_fixes:
        new_features = [i for i in completed if i.priority in ("Critical", "High")]
        enhancements = [i for i in completed if i.priority == "Medium"]
        bug_fixes = [i for i in completed if i.priority == "Low"]

    today = release.release_date or date.today().isoformat()
    prepared_by = ""
    pm = db.query(User).filter(User.id == project.project_manager_id).first() if project.project_manager_id else None
    if pm:
        prepared_by = pm.name

    L = []  # lines

    # ── Header metadata ──────────────────────────────────────────────
    L.append(f"# {project.name}")
    L.append("## Release Notes")
    L.append("")
    L.append("| Field | Value |")
    L.append("|---|---|")
    L.append(f"| Product | {project.name} |")
    L.append(f"| Release Version | v{release.version.lstrip('v')} |")
    L.append(f"| Release Type | {release_type} |")
    L.append(f"| Release Date | {today} |")
    L.append("| Environment | Production |")
    L.append(f"| Git Tag / Image Tag | v{release.version.lstrip('v')} |")
    L.append(f"| Prepared By (PM) | {prepared_by or '—'} |")
    L.append(f"| Status | {release.status} |")
    L.append(f"| Release Cycle / Train | {today[:7]} monthly train |")
    L.append(f"| Previous Stable Tag | {prev_tag or '—'} |")
    L.append("")

    # ── 1. Release Summary ───────────────────────────────────────────
    L.append("## 1. Release Summary")
    if release.description:
        L.append(release.description)
    else:
        summary_parts = []
        if new_features:
            summary_parts.append(f"{len(new_features)} new feature(s)")
        if enhancements:
            summary_parts.append(f"{len(enhancements)} enhancement(s)")
        if bug_fixes:
            summary_parts.append(f"{len(bug_fixes)} bug fix(es)")
        if in_progress:
            summary_parts.append(f"{len(in_progress)} item(s) carried over")
        summary = ", ".join(summary_parts) if summary_parts else "No items in this release."
        L.append(f"This release delivers {summary}.")
    L.append("")

    # ── 2. New Features ──────────────────────────────────────────────
    L.append("## 2. New Features")
    L.append("Customer-visible new capabilities. Reference the BRD / story ID.")
    L.append("")
    L.append("| Ref / Story ID | Feature | User Impact |")
    L.append("|---|---|---|")
    if new_features:
        for item in new_features:
            impact = (item.description or "")[:100]
            L.append(f"| {item.id} | {item.title} | {impact} |")
    else:
        L.append("| — | No new features in this release | — |")
    L.append("")

    # ── 3. Enhancements & Improvements ───────────────────────────────
    L.append("## 3. Enhancements & Improvements")
    L.append("Changes to existing behaviour — performance, UX, usability.")
    L.append("")
    L.append("| Ref / Story ID | Enhancement | User Impact |")
    L.append("|---|---|---|")
    if enhancements:
        for item in enhancements:
            impact = (item.description or "")[:100]
            L.append(f"| {item.id} | {item.title} | {impact} |")
    else:
        L.append("| — | No enhancements in this release | — |")
    L.append("")

    # ── 4. Bug Fixes ─────────────────────────────────────────────────
    L.append("## 4. Bug Fixes")
    L.append("Defects resolved in this release. Severity: Critical / High / Medium / Low.")
    L.append("")
    L.append("| Ref / Bug ID | Description | Severity |")
    L.append("|---|---|---|")
    if bug_fixes:
        for item in bug_fixes:
            L.append(f"| {item.id} | {item.title} | {item.priority or 'Medium'} |")
    else:
        L.append("| — | No bug fixes in this release | — |")
    L.append("")

    # ── 5. Hotfixes Included ─────────────────────────────────────────
    hotfix_items = [i for i in completed if "hotfix" in (i.item_type or "").lower()]
    L.append("## 5. Hotfixes Included")
    L.append("Only if this release rolls up prior emergency hotfixes. Otherwise delete this section.")
    L.append("")
    if hotfix_items:
        L.append("| Hotfix Tag | Description | Original Incident |")
        L.append("|---|---|---|")
        for item in hotfix_items:
            L.append(f"| v{release.version.lstrip('v')} | {item.title} | {item.id} |")
    else:
        L.append("_No hotfixes rolled up in this release._")
    L.append("")

    # ── 6. Breaking Changes & Migration Notes ────────────────────────
    breaking = [i for i in completed if "breaking" in (i.item_type or "").lower() or "migration" in (item.description or "").lower()]
    L.append("## 6. Breaking Changes & Migration Notes")
    L.append("Anything that requires action from consumers/integrators, config changes, or data migration. State 'None' if not applicable.")
    L.append("")
    if breaking:
        for item in breaking:
            L.append(f"- **{item.title}**: {item.description or ''}")
    else:
        L.append("None.")
    L.append("")

    # ── 7. Known Issues & Limitations ────────────────────────────────
    known = in_progress  # items still in progress are known limitations
    L.append("## 7. Known Issues & Limitations")
    L.append("Known defects or limitations shipping with this release, with a workaround if one exists.")
    L.append("")
    L.append("| Ref | Known Issue | Workaround / Planned Fix |")
    L.append("|---|---|---|")
    if known:
        for item in known:
            L.append(f"| {item.id} | {item.title} — {item.current_phase} ({item.status}) | Targeted for next release |")
    else:
        L.append("| — | No known issues | — |")
    L.append("")

    # ── 8. Deployment Details ────────────────────────────────────────
    L.append("## 8. Deployment Details")
    L.append("Filled by DevOps at release time. These fields make the release traceable and rollback-ready.")
    L.append("")
    L.append("| Field | Value |")
    L.append("|---|---|")
    L.append(f"| Git Commit / SHA | {'—'} |")
    L.append(f"| Container Image Tag | {'—'} |")
    L.append(f"| ArgoCD App / Sync Status | {'—'} |")
    L.append(f"| Previous Stable Tag (rollback target) | {prev_tag or '—'} |")
    L.append("| Config / Secret Changes (Vault) | None |")
    L.append("| DB Migrations (reversible?) | None |")
    L.append("| Monitoring Dashboards | Prometheus / Sentry / Uptime |")
    L.append("")

    # ── 9. Rollback Reference ────────────────────────────────────────
    L.append("## 9. Rollback Reference")
    L.append("Link to the tested rollback script/plan for this release (SHIP repo).")
    L.append("")
    L.append(f"_Rollback runbook to be linked by DevOps at release time. Previous stable tag: {prev_tag or '—'}._")
    L.append("")

    # ── 10. Sign-Offs ────────────────────────────────────────────────
    L.append("## 10. Sign-Offs")
    L.append("Aligned to the RACI gates. All four must be captured before a Production release is marked Released.")
    L.append("")
    L.append("| Role | Name | Date / Approval |")
    L.append("|---|---|---|")
    signoffs = _get_signoffs(release, db)
    for s in signoffs:
        status_icon = "✅" if s["status"] == "Approved" else "⏳"
        L.append(f"| {s['role']} | {s['name']} | {status_icon} {s['date']} |")
    L.append("")
    L.append("---")
    L.append("*Document version: Release Notes Template v1.1 · aligned to Release Process v3.4, Versioning & Release Cadence v1.2*")

    return "\n".join(L)


@router.post("/releases/{release_id}/generate-notes", response_model=dict)
def generate_release_notes(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-generate structured release notes matching Release_Notes_Template_v1.1.docx."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    project = db.query(Project).filter(Project.id == release.project_id).first()

    # Gather backlog items
    items = []
    for ri in release.items:
        bi = db.query(BacklogItem).filter(BacklogItem.id == ri.backlog_item_id).first()
        if bi:
            items.append(bi)

    # Milestone
    milestone = None
    if release.milestone_id:
        ms = db.query(Milestone).filter(Milestone.id == release.milestone_id).first()
        if ms:
            milestone = {"id": ms.id, "title": ms.title, "target_date": str(ms.target_date) if ms.target_date else None}

    # Find previous stable tag
    all_releases = db.query(Release).filter(Release.project_id == release.project_id).all()
    prev_tag = None
    def parse_version(v):
        try:
            parts = v.lstrip("v").split(".")
            return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, int(parts[2]) if len(parts) > 2 else 0)
        except (ValueError, IndexError):
            return (0, 0, 0)
    released = [r for r in all_releases if r.status == "Released" and r.id != release.id]
    if released:
        prev_tag = f"v{max(released, key=lambda r: parse_version(r.version)).version.lstrip('v')}"

    notes = _build_release_notes(release, project, items, milestone, prev_tag, db)
    release.release_notes = notes
    db.commit()

    done_phases = ["Pre-Release", "Release", "Post-Release", "Retrospective"]
    completed = len([i for i in items if i.current_phase in done_phases])
    return {"release_notes": notes, "total_items": len(items), "completed": completed}


def _get_signoffs(release, db):
    """Collect sign-off data from actual approval records for this release.

    Maps the V-cycle phase gate approvals to the 4 sign-off roles in the template:
    - QA Lead (QA sign-off)        ← Testing gate
    - Product Manager (UAT sign-off) ← UAT gate
    - Tech Lead (version/tag)       ← In Progress / Pre-Release gate
    - DevOps Lead (deployment)      ← Released gate
    """
    # Template sign-off roles (in order) — aligned to RACI Matrix v2.3
    signoff_roles = [
        ("QA Lead (QA sign-off)", "QA Lead"),
        ("Product Manager (UAT sign-off)", "Product Manager"),
        ("Tech Lead (version/tag)", "Tech Lead"),
        ("DevOps Lead (deployment)", "DevOps Lead"),
    ]

    # Fetch all approval steps for this release
    approval_requests = db.query(ApprovalRequest).filter(
        ApprovalRequest.release_id == release.id,
    ).all()

    # Build a map: role_name → (approver_name, date, status)
    approval_map = {}
    for ar in approval_requests:
        steps = db.query(ApprovalStep).filter(
            ApprovalStep.request_id == ar.id,
        ).order_by(ApprovalStep.step_order).all()
        for s in steps:
            approver_name = "—"
            if s.approver_id:
                u = db.query(User).filter(User.id == s.approver_id).first()
                if u:
                    approver_name = u.name
            # Only record approved steps, prefer the latest
            if s.status == "Approved":
                key = s.role_name
                approval_map[key] = (approver_name, s.decided_at or "—", "Approved")

    # Build the sign-off rows
    result = []
    for template_role, gate_role in signoff_roles:
        if gate_role in approval_map:
            name, date_str, status = approval_map[gate_role]
            # Clean up date format
            if date_str and date_str != "—":
                # Try to format nicely
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    date_str = dt.strftime("%d-%b-%Y")
                except (ValueError, TypeError):
                    pass
            result.append({"role": template_role, "name": name, "date": date_str, "status": status})
        else:
            result.append({"role": template_role, "name": "—", "date": "—", "status": "Pending"})

    return result


def _build_docx(release, project, items, prev_tag, db):
    """Build a DOCX that matches Release_Notes_Template_v1.1.docx exactly."""
    from datetime import date, datetime
    from io import BytesIO

    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    done_phases = ["Pre-Release", "Release", "Post-Release", "Retrospective"]
    completed = [i for i in items if i.current_phase in done_phases]
    in_progress = [i for i in items if i.current_phase not in done_phases]

    # Determine release type
    ver_parts = release.version.lstrip("v").split(".")
    release_type = "Minor / Feature"
    if len(ver_parts) >= 3:
        try:
            patch_n = int(ver_parts[2])
            minor_n = int(ver_parts[1])
            major_n = int(ver_parts[0])
            if patch_n > 0:
                release_type = "Patch / Hotfix"
            elif minor_n == 0 and major_n > 0:
                release_type = "Major / Breaking"
        except (ValueError, IndexError):
            pass

    # Categorize items
    new_features = [i for i in completed if i.item_type and i.item_type.lower() in ("feature", "story", "user story")]
    enhancements = [i for i in completed if i.item_type and i.item_type.lower() in ("enhancement", "improvement", "task")]
    bug_fixes = [i for i in completed if i.item_type and i.item_type.lower() in ("bug", "defect", "fix")]
    if not new_features and not enhancements and not bug_fixes:
        new_features = [i for i in completed if i.priority in ("Critical", "High")]
        enhancements = [i for i in completed if i.priority == "Medium"]
        bug_fixes = [i for i in completed if i.priority == "Low"]

    # Prepared by
    prepared_by = "—"
    if project.project_manager_id:
        pm = db.query(User).filter(User.id == project.project_manager_id).first()
        if pm:
            prepared_by = pm.name

    today = release.release_date or date.today().isoformat()
    try:
        dt = datetime.fromisoformat(today)
        today_fmt = dt.strftime("%d-%b-%Y")
    except (ValueError, TypeError):
        today_fmt = today

    # ── Create document ──────────────────────────────────────────────
    doc = Document()

    # Set margins
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # Set default font
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(11)

    def _set_cell_shading(cell, color_hex):
        """Set cell background color."""
        shading = cell._element.get_or_add_tcPr()
        shd = shading.makeelement(qn('w:shd'), {
            qn('w:val'): 'clear',
            qn('w:color'): 'auto',
            qn('w:fill'): color_hex,
        })
        shading.append(shd)

    def _set_cell_text(cell, text, bold=False, size=10, color=None, italic=False):
        """Set cell text with formatting."""
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run(str(text) if text else "")
        run.bold = bold
        run.italic = italic
        run.font.size = Pt(size)
        run.font.name = 'Calibri'
        if color:
            run.font.color.rgb = RGBColor(*color)

    def _add_field_value_table(rows):
        """Add a 2-column field/value table like the template header."""
        table = doc.add_table(rows=len(rows), cols=2)
        table.style = 'Table Grid'
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        for idx, (field, value) in enumerate(rows):
            _set_cell_text(table.rows[idx].cells[0], field, bold=True, size=10, color=(0x4a, 0x55, 0x68))
            _set_cell_text(table.rows[idx].cells[1], value, size=10)
            _set_cell_shading(table.rows[idx].cells[0], 'F3F4F6')
        # Set column widths
        for row in table.rows:
            row.cells[0].width = Cm(5.5)
            row.cells[1].width = Cm(11)
        return table

    def _add_data_table(headers, rows, col_widths=None):
        """Add a data table with styled header row and optional grey example row."""
        table = doc.add_table(rows=1 + len(rows), cols=len(headers))
        table.style = 'Table Grid'
        # Header row
        for c_idx, h in enumerate(headers):
            _set_cell_text(table.rows[0].cells[c_idx], h, bold=True, size=9, color=(0xFF, 0xFF, 0xFF))
            _set_cell_shading(table.rows[0].cells[c_idx], '4F46E5')
        # Data rows
        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                _set_cell_text(table.rows[r_idx + 1].cells[c_idx], val, size=9)
        # Column widths
        if col_widths:
            for row in table.rows:
                for c_idx, w in enumerate(col_widths):
                    if c_idx < len(row.cells):
                        row.cells[c_idx].width = Cm(w)
        return table

    # ── Title ────────────────────────────────────────────────────────
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(project.name)
    run.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(0x4F, 0x46, 0xE5)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("Release Notes")
    run.bold = True
    run.font.size = Pt(16)
    run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    doc.add_paragraph("")

    # ── Header metadata table ────────────────────────────────────────
    header_rows = [
        ("Product", project.name),
        ("Release Version", f"v{release.version.lstrip('v')}"),
        ("Release Type", release_type),
        ("Release Date", today_fmt),
        ("Environment", "Production"),
        ("Git Tag / Image Tag", f"v{release.version.lstrip('v')}"),
        ("Prepared By (PM)", prepared_by),
        ("Status", release.status),
        ("Release Cycle / Train", f"{today[:7]} monthly train"),
        ("Previous Stable Tag", prev_tag or "—"),
    ]
    _add_field_value_table(header_rows)

    doc.add_paragraph("")

    # ── 1. Release Summary ───────────────────────────────────────────
    doc.add_heading("1. Release Summary", level=2)
    p = doc.add_paragraph()
    if release.description:
        p.add_run(release.description)
    else:
        parts = []
        if new_features: parts.append(f"{len(new_features)} new feature(s)")
        if enhancements: parts.append(f"{len(enhancements)} enhancement(s)")
        if bug_fixes: parts.append(f"{len(bug_fixes)} bug fix(es)")
        if in_progress: parts.append(f"{len(in_progress)} item(s) carried over")
        summary = ", ".join(parts) if parts else "No items in this release."
        p.add_run(f"This release delivers {summary}.")

    # ── 2. New Features ──────────────────────────────────────────────
    doc.add_heading("2. New Features", level=2)
    doc.add_paragraph("Customer-visible new capabilities. Reference the BRD / story ID.")
    if new_features:
        rows = [(str(i.id), i.title, (i.description or "")[:100]) for i in new_features]
    else:
        rows = [("—", "No new features in this release", "—")]
    _add_data_table(["Ref / Story ID", "Feature", "User Impact"], rows, col_widths=[3, 6, 7])

    # ── 3. Enhancements & Improvements ───────────────────────────────
    doc.add_heading("3. Enhancements & Improvements", level=2)
    doc.add_paragraph("Changes to existing behaviour — performance, UX, usability.")
    if enhancements:
        rows = [(str(i.id), i.title, (i.description or "")[:100]) for i in enhancements]
    else:
        rows = [("—", "No enhancements in this release", "—")]
    _add_data_table(["Ref / Story ID", "Enhancement", "User Impact"], rows, col_widths=[3, 6, 7])

    # ── 4. Bug Fixes ─────────────────────────────────────────────────
    doc.add_heading("4. Bug Fixes", level=2)
    doc.add_paragraph("Defects resolved in this release. Severity: Critical / High / Medium / Low.")
    if bug_fixes:
        rows = [(str(i.id), i.title, i.priority or "Medium") for i in bug_fixes]
    else:
        rows = [("—", "No bug fixes in this release", "—")]
    _add_data_table(["Ref / Bug ID", "Description", "Severity"], rows, col_widths=[3, 9, 4])

    # ── 5. Hotfixes Included ─────────────────────────────────────────
    hotfix_items = [i for i in completed if "hotfix" in (i.item_type or "").lower()]
    doc.add_heading("5. Hotfixes Included", level=2)
    doc.add_paragraph("Only if this release rolls up prior emergency hotfixes. Otherwise delete this section.")
    if hotfix_items:
        rows = [(f"v{release.version.lstrip('v')}", i.title, str(i.id)) for i in hotfix_items]
        _add_data_table(["Hotfix Tag", "Description", "Original Incident"], rows, col_widths=[3, 8, 5])
    else:
        p = doc.add_paragraph()
        run = p.add_run("No hotfixes rolled up in this release.")
        run.italic = True
        run.font.size = Pt(10)

    # ── 6. Breaking Changes & Migration Notes ────────────────────────
    doc.add_heading("6. Breaking Changes & Migration Notes", level=2)
    doc.add_paragraph("Anything that requires action from consumers/integrators, config changes, or data migration. State 'None' if not applicable.")
    breaking = [i for i in completed if "breaking" in (i.item_type or "").lower() or "migration" in (i.description or "").lower()]
    if breaking:
        for item in breaking:
            p = doc.add_paragraph(style='List Bullet')
            run = p.add_run(f"{item.title}: ")
            run.bold = True
            p.add_run(item.description or "")
    else:
        doc.add_paragraph("None.")

    # ── 7. Known Issues & Limitations ────────────────────────────────
    doc.add_heading("7. Known Issues & Limitations", level=2)
    doc.add_paragraph("Known defects or limitations shipping with this release, with a workaround if one exists.")
    if in_progress:
        rows = [(str(i.id), f"{i.title} — {i.current_phase} ({i.status})", "Targeted for next release") for i in in_progress]
    else:
        rows = [("—", "No known issues", "—")]
    _add_data_table(["Ref", "Known Issue", "Workaround / Planned Fix"], rows, col_widths=[2, 8, 6])

    # ── 8. Deployment Details ────────────────────────────────────────
    doc.add_heading("8. Deployment Details", level=2)
    doc.add_paragraph("Filled by DevOps at release time. These fields make the release traceable and rollback-ready.")
    deploy_rows = [
        ("Git Commit / SHA", "—"),
        ("Container Image Tag", "—"),
        ("ArgoCD App / Sync Status", "—"),
        ("Previous Stable Tag (rollback target)", prev_tag or "—"),
        ("Config / Secret Changes (Vault)", "None"),
        ("DB Migrations (reversible?)", "None"),
        ("Monitoring Dashboards", "Prometheus / Sentry / Uptime"),
    ]
    _add_field_value_table(deploy_rows)

    # ── 9. Rollback Reference ────────────────────────────────────────
    doc.add_heading("9. Rollback Reference", level=2)
    doc.add_paragraph("Link to the tested rollback script/plan for this release (SHIP repo).")
    p = doc.add_paragraph()
    run = p.add_run(f"Rollback runbook to be linked by DevOps at release time. Previous stable tag: {prev_tag or '—'}.")
    run.italic = True

    # ── 10. Sign-Offs ────────────────────────────────────────────────
    doc.add_heading("10. Sign-Offs", level=2)
    doc.add_paragraph("Aligned to the RACI gates. All four must be captured before a Production release is marked Released.")

    signoffs = _get_signoffs(release, db)
    signoff_rows = [(s["role"], s["name"], s["date"]) for s in signoffs]
    signoff_table = _add_data_table(["Role", "Name", "Date / Approval"], signoff_rows, col_widths=[6, 5, 5])
    # Color-code the status column — shade approved rows green, pending rows amber
    for r_idx, s in enumerate(signoffs):
        row = signoff_table.rows[r_idx + 1]
        if s["status"] == "Approved":
            _set_cell_shading(row.cells[2], 'D1FAE5')  # emerald-100
        else:
            _set_cell_shading(row.cells[2], 'FEF3C7')  # amber-100

    # ── Footer ───────────────────────────────────────────────────────
    doc.add_paragraph("")
    p = doc.add_paragraph()
    run = p.add_run("Document version: Release Notes Template v1.1  ·  aligned to Release Process v3.4, Versioning & Release Cadence v1.2")
    run.italic = True
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0x9C, 0xA3, 0xAF)

    # Save to BytesIO
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


@router.get("/releases/{release_id}/download-notes")
def download_release_notes(
    release_id: int,
    token: str = None,
    db: Session = Depends(get_db),
):
    """Download release notes as a DOCX file matching Release_Notes_Template_v1.1.docx."""
    # Authenticate via query param token (for window.open downloads)
    from app.dependencies import get_current_user
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    current_user = get_current_user(token, db)

    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    if not release.release_notes:
        raise HTTPException(status_code=400, detail="Generate release notes first")

    project = db.query(Project).filter(Project.id == release.project_id).first()

    # Gather items
    items = []
    for ri in release.items:
        bi = db.query(BacklogItem).filter(BacklogItem.id == ri.backlog_item_id).first()
        if bi:
            items.append(bi)

    # Find previous stable tag
    all_releases = db.query(Release).filter(Release.project_id == release.project_id).all()
    prev_tag = None
    def parse_version(v):
        try:
            parts = v.lstrip("v").split(".")
            return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, int(parts[2]) if len(parts) > 2 else 0)
        except (ValueError, IndexError):
            return (0, 0, 0)
    released = [r for r in all_releases if r.status == "Released" and r.id != release.id]
    if released:
        prev_tag = f"v{max(released, key=lambda r: parse_version(r.version)).version.lstrip('v')}"

    buf = _build_docx(release, project, items, prev_tag, db)

    from fastapi.responses import StreamingResponse
    filename = f"Release_Notes_v{release.version.lstrip('v')}_{project.name.replace(' ', '_')}.docx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/releases/{release_id}/share", response_model=dict)
def share_release_notes(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark release notes as shared with project stakeholders."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    if not release.release_notes:
        raise HTTPException(status_code=400, detail="Generate release notes first")

    # Get project stakeholders
    from app.models.stakeholder import Stakeholder
    stakeholders = db.query(Stakeholder).filter(Stakeholder.project_id == release.project_id).all()

    # Get assigned users (RACI roles)
    from app.models.role_assignment import RoleAssignment
    assignments = db.query(RoleAssignment).filter(RoleAssignment.project_id == release.project_id).all()

    shared_with = []
    for s in stakeholders:
        shared_with.append({"name": s.name, "role": s.role or "Stakeholder", "email": s.email or ""})
    for a in assignments:
        u = db.query(User).filter(User.id == a.user_id).first()
        role = db.query(Role).filter(Role.id == a.role_id).first() if hasattr(a, 'role_id') else None
        if u:
            role_name = role.name if role else (getattr(a, 'role_name', None) or "Team Member")
            shared_with.append({"name": u.name, "role": role_name, "email": u.email})

    return {
        "message": f"Release notes shared with {len(shared_with)} stakeholder(s)",
        "shared_with": shared_with,
        "release_version": release.version,
        "release_name": release.name,
    }


# ── Sign-off PDF ────────────────────────────────────────────────────────────

@router.get("/releases/{release_id}/signoff-pdf")
def download_signoff_pdf(
    request: Request,
    release_id: int,
    token: str = None,
    db: Session = Depends(get_db),
):
    """Generate a PDF document with all phase sign-offs for this release."""
    from io import BytesIO

    from fastapi.responses import StreamingResponse
    from fpdf import FPDF

    # Authenticate via query param token (for window.open downloads)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    current_user = get_current_user(token, db)

    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    project = db.query(Project).filter(Project.id == release.project_id).first()

    # Get items linked to this release
    from app.models.release import ReleaseItem
    release_items = db.query(ReleaseItem).filter(ReleaseItem.release_id == release.id).all()
    item_ids = [ri.backlog_item_id for ri in release_items]
    items = db.query(BacklogItem).filter(BacklogItem.id.in_(item_ids)).all() if item_ids else []

    # Compute V-cycle index
    v_cycle_index = -1
    for i, (phase, _, _) in enumerate(V_CYCLE):
        if release.status == phase:
            v_cycle_index = i
            break

    # Get phase gates
    phase_gates = _compute_phase_gates(release, [{"current_phase": i.current_phase, "is_done": i.status == "Done"} for i in items], v_cycle_index)

    # Get approvals
    approval_requests = db.query(ApprovalRequest).filter(
        ApprovalRequest.release_id == release.id
    ).order_by(ApprovalRequest.id).all()

    # Build PDF
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 27, 75)  # indigo-950
    pdf.cell(0, 8, "Release Sign-off Document", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Release info table
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(51, 51, 51)

    info_data = [
        ("Project", project.name if project else "-"),
        ("Release", f"{release.name} (v{release.version})"),
        ("Status", release.status),
        ("Release Date", release.release_date or "-"),
        ("Target Date", release.target_date or "-"),
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
    ]
    for label, value in info_data:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(35, 5, label + ":")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, str(value), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(3)

    # Phase Gates table header
    pdf.set_fill_color(240, 240, 245)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(25, 6, "Phase", border=1, fill=True)
    pdf.cell(30, 6, "RACI Role", border=1, fill=True)
    pdf.cell(20, 6, "Status", border=1, fill=True)
    pdf.cell(35, 6, "Approver", border=1, fill=True)
    pdf.cell(25, 6, "Date", border=1, fill=True)
    pdf.cell(0, 6, "Checklist", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

    # Phase Gates rows
    for gate in phase_gates:
        # Find matching approval
        approver_name = "-"
        decided_at = "-"
        for ar in approval_requests:
            if ar.target_phase == gate["phase"]:
                steps = db.query(ApprovalStep).filter(ApprovalStep.request_id == ar.id).all()
                for s in steps:
                    if s.approver_id:
                        u = db.query(User).filter(User.id == s.approver_id).first()
                        if u:
                            approver_name = u.name
                    if s.decided_at:
                        decided_at = str(s.decided_at)[:10]

        gate_status = "Signed Off" if gate["reached"] else ("Pending" if gate["phase"] == release.status else "Upcoming")
        checked_count = sum(1 for item in gate["checklist"] if item["checked"])
        total = len(gate["checklist"])
        checklist_str = f"{checked_count}/{total} checked"

        pdf.set_font("Helvetica", "", 8)
        pdf.cell(25, 6, gate["phase"], border=1)
        pdf.cell(30, 6, gate["role"], border=1)
        pdf.cell(20, 6, gate_status, border=1)
        pdf.cell(35, 6, approver_name, border=1)
        pdf.cell(25, 6, decided_at, border=1)
        pdf.cell(0, 6, checklist_str, border=1, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(3)

    # Detailed checklist per gate
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(30, 27, 75)
    pdf.cell(0, 6, "Phase Gate Checklists", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    for gate in phase_gates:
        gate_status = "Signed Off" if gate["reached"] else ("Pending" if gate["phase"] == release.status else "Upcoming")
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(51, 51, 51)
        pdf.cell(0, 5, f"{gate['phase']} Gate - {gate['role']} ({gate_status})", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(80, 80, 80)
        for item in gate["checklist"]:
            mark = "[x]" if item["checked"] else "[ ]"
            pdf.cell(5, 4, "")
            pdf.cell(0, 4, f"{mark} {item['text']}", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(1)

    # Release items
    if items:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(30, 27, 75)
        pdf.cell(0, 6, f"Release Items ({len(items)})", new_x="LMARGIN", new_y="NEXT")

        pdf.set_fill_color(240, 240, 245)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(15, 5, "ID", border=1, fill=True)
        pdf.cell(60, 5, "Title", border=1, fill=True)
        pdf.cell(25, 5, "Type", border=1, fill=True)
        pdf.cell(30, 5, "Phase", border=1, fill=True)
        pdf.cell(0, 5, "Status", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

        for item in items:
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(15, 5, f"#{item.id}", border=1)
            pdf.cell(60, 5, str(item.title)[:40], border=1)
            pdf.cell(25, 5, str(item.item_type), border=1)
            pdf.cell(30, 5, str(item.current_phase), border=1)
            pdf.cell(0, 5, str(item.status), border=1, new_x="LMARGIN", new_y="NEXT")

    # Footer
    pdf.ln(5)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 4, f"This document was auto-generated by the PMO System on {datetime.now().strftime('%Y-%m-%d at %H:%M')}.", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 4, "Sign-offs are captured automatically as the release advances through V-cycle approval gates per the RACI matrix.", new_x="LMARGIN", new_y="NEXT")

    # Output
    output = BytesIO()
    pdf.output(output)
    output.seek(0)

    filename = f"signoff_{release.version}_{datetime.now().strftime('%Y%m%d')}.pdf"

    # Check if this is a view (inline) or download (attachment)
    view_mode = request.query_params.get("view", "0") == "1"
    disposition = "inline" if view_mode else "attachment"

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )
