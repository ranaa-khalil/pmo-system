"""Release machine — the ONE advance state machine (Rethink v2 F1).

advance_release_phase and advance_backlog_item_phase are the advance machine
for the whole system: the releases router (POST /releases/{id}/advance) and
the backlog router (POST /backlog/{id}/advance) both delegate here, so a
behavior change lands once — and a future bulk advance calls these same
functions instead of looping the machine into a third copy.

The bodies are a VERBATIM move from the two router functions they replace:
same status guards, same V-cycle walk, same RACI gate flow (created →
pending → approved/rejected branches), same effective-template reads
(get_effective_lifecycle with the tenant id, Rethink v2 C1), same GitHub
sync on the build phase, and the log_activity + artifact-chain entries in
the same order with the same payloads — the chain never forks.

The helpers the machine calls (_create_phase_approval and
_sync_release_items_to_phase in routers/releases.py — the former is
imported there by the locked approvals/guest_links routers — and
_auto_export_to_github in routers/backlog.py) stay in place; the machine
imports them lazily at call time, so a bulk endpoint reuses the exact same
gate-creation path. Tenant scoping and the 400 strings are byte-identical
to the router paths the existing tests assert; the tenant-scoped fetch and
the 404 stay in the routers (request glue).
"""
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release
from app.models.tenant import Tenant
from app.models.user import User
from app.services.notifications import log_activity


def advance_release_phase(db: Session, tenant: Tenant, user: User, release: Release) -> dict:
    """Advance a release to the next V-cycle phase (the service machine).

    Instead of immediately advancing, this creates an approval request routed
    to the RACI role that gate-keeps the CURRENT phase. The release advances
    only when that role approves (see approve_step in approvals.py).

    If an approval is already pending for this release, returns its status.
    If the approval was already approved, advances the release immediately and
    creates the next phase's approval.
    """
    from app.routers.releases import (
        PHASE_GATE_ROLES,
        V_CYCLE,
        _create_phase_approval,
        _sync_release_items_to_phase,
    )

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

    # Rethink v2 C1 — the vocabulary check reads the EFFECTIVE lifecycle: a
    # tenant's template row overrides the release-stage ladder, so a release
    # parked on one of the template's release stages advances along the
    # TEMPLATE's ladder (no RACI gate maps to template stages — they advance
    # directly). Tenants without a template row keep the built-in V-cycle
    # verbatim (byte-identical behavior).
    if current_idx < 0:
        from app.services.lifecycle import get_effective_lifecycle

        project = db.query(Project).filter(Project.id == release.project_id).first()
        eff = get_effective_lifecycle(db, tenant.id, getattr(project, "project_type", None))
        template_stages = eff["release_stages"]
        if eff["source"] == "template" and release.status in template_stages:
            stage_idx = template_stages.index(release.status)
            if stage_idx >= len(template_stages) - 1:
                raise HTTPException(
                    status_code=400,
                    detail=f"Release is already in the final release stage ({template_stages[-1]})",
                )
            next_phase = template_stages[stage_idx + 1]
        else:
            raise HTTPException(status_code=400, detail=f"Unknown status: {release.status}")
    else:
        next_phase = V_CYCLE[current_idx + 1][0]

    # Check if there's already an approval for this release + target phase
    existing = db.query(ApprovalRequest).filter(
        ApprovalRequest.release_id == release.id,
        ApprovalRequest.tenant_id == tenant.id,
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
            next_approval = _create_phase_approval(db, release, user, tenant.id)
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
        tenant_id=tenant.id,
        project_id=release.project_id,
        title=f"Release {release.version}: {release.status} → {next_phase}",
        description=gate_desc + "\n\nChecklist:\n" + "\n".join(f"☐ {item}" for item in gate_checklist),
        request_type="release",
        requested_by=user.id,
        release_id=release.id,
        target_phase=next_phase,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    step = ApprovalStep(
        tenant_id=tenant.id,
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


def advance_backlog_item_phase(db: Session, tenant: Tenant, user: User, item: BacklogItem) -> BacklogItem:
    """Advance a backlog item to the next phase of its project's lifecycle.

    Dynamic: the phase vocabulary comes from the project's EFFECTIVE
    lifecycle — the tenant's lifecycle template row when one exists, the
    built-in template otherwise (Rethink v2 C1) — never a hardcoded list. The
    release stages stay release-level for every template.
    """
    from app.models.backlog_item import RELEASE_PHASES
    from app.routers.backlog import _auto_export_to_github
    from app.services.lifecycle import get_effective_lifecycle

    project = db.query(Project).filter(Project.id == item.project_id).first()
    project_type = project.project_type if project else None

    # Items in release-level phases (UAT, Pre-Release, ...) are managed by the
    # release workflow — advancing must not reset them.
    if item.current_phase in RELEASE_PHASES:
        return item

    # Rethink v2 C1: the vocabulary check reads the EFFECTIVE lifecycle — the
    # tenant's template row overrides the built-in, so a custom ADLC template
    # drives the advance chain. Tenants without a template row keep the
    # built-in (byte-identical to the old item_phases()/release_stages() reads).
    eff = get_effective_lifecycle(db, tenant.id, project_type)
    phases = eff["item_phases"]
    release_level = eff["release_stages"]
    if item.current_phase in release_level:
        return item
    if item.current_phase not in phases:
        # Legacy phase value from another template — normalise to the project's
        # template by jumping to its first phase.
        item.current_phase = phases[0]
        db.commit()
        db.refresh(item)
        return item

    current_idx = phases.index(item.current_phase)
    if current_idx >= len(phases) - 1:
        raise HTTPException(
            status_code=400,
            detail=f"Item is at the final item phase ({phases[-1]}). Add it to a release to continue through the release stages.",
        )

    item.current_phase = phases[current_idx + 1]
    if item.status == "Draft":
        item.status = "In Progress"

    # GitHub sync on entering the build phase for this template
    from app.services.lifecycle import GITHUB_SYNC_PHASES
    sync_phases = GITHUB_SYNC_PHASES.get(project_type or "software", ["Development"])
    if item.current_phase in sync_phases and not item.github_issue_number:
        _auto_export_to_github(db, item, tenant.id)

    db.commit()
    db.refresh(item)

    log_activity(db, user.id, user.name, item.project_id,
                 "backlog_item", item.id, "advanced",
                 f"Advanced '{item.title}' to {item.current_phase}")

    # Artifact Chain: the phase move is an immutable, hash-linked entry
    from app.services.artifact_chain import append_artifact
    append_artifact(
        db, tenant.id, "backlog_item", item.id, "advanced",
        actor_id=user.id, actor_name=user.name,
        payload={"title": item.title, "to_phase": item.current_phase, "status": item.status},
    )

    # The audit writes above are flush-only — commit them or they roll back
    # when the request session closes (live-only failure; the suite is green
    # either way because same-session tests read flushed rows in-transaction).
    db.commit()

    return item
