"""Approval workflow API router — RACI gate approval chains."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.approval import (
    ApprovalDecision,
    ApprovalRequestCreate,
    ApprovalRequestWithStepsResponse,
)
from app.services.notifications import (
    log_activity,
    notify_approval_created,
    notify_approval_result,
)
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["approvals"])


def _enrich_steps(db: Session, request: ApprovalRequest, tenant_id: int):
    """Add approver_name to each step by resolving the FK."""
    steps = db.query(ApprovalStep).filter(
        ApprovalStep.request_id == request.id,
        ApprovalStep.tenant_id == tenant_id,
    ).order_by(ApprovalStep.step_order).all()
    for s in steps:
        s.approver_name = None
        if s.approver_id:
            user = db.query(User).filter(User.id == s.approver_id).first()
            s.approver_name = user.name if user else None
    request.steps = steps
    return request


@router.post("/projects/{project_id}/approvals", response_model=ApprovalRequestWithStepsResponse, status_code=201)
def create_approval_request(
    project_id: int,
    req: ApprovalRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create an approval request with a chain of RACI steps."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "approvals")

    tid = current_tenant.id
    if not db.query(Project).filter(Project.id == project_id, Project.tenant_id == tid).first():
        raise HTTPException(status_code=404, detail="Project not found")
    if req.project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    if not req.steps:
        raise HTTPException(status_code=400, detail="At least one approval step is required")

    request = ApprovalRequest(
        project_id=project_id,
        title=req.title,
        description=req.description,
        request_type=req.request_type,
        requested_by=current_user.id,
        release_id=req.release_id,
        target_phase=req.target_phase,
        tenant_id=tid,
    )
    db.add(request)
    db.commit()
    db.refresh(request)

    for step_data in req.steps:
        step = ApprovalStep(
            request_id=request.id,
            step_order=step_data.step_order,
            role_name=step_data.role_name,
            approver_id=step_data.approver_id,
            tenant_id=tid,
        )
        db.add(step)
    db.commit()
    db.refresh(request)

    # Load steps for response (with approver names)
    result = _enrich_steps(db, request, tid)

    # Notify the first approver
    first_step = result.steps[0] if result.steps else None
    if first_step and first_step.approver_id:
        release_name = ""
        if request.release_id:
            from app.models.release import Release
            rel = db.query(Release).filter(Release.id == request.release_id, Release.tenant_id == tid).first()
            release_name = f"{rel.version} — {rel.name}" if rel else ""
        notify_approval_created(
            db, request.id, first_step.role_name,
            first_step.approver_id, project_id, release_name,
        )
        log_activity(db, current_user.id, current_user.name, project_id,
                     "approval", request.id, "created",
                     f"Created approval request: {request.title}")

    db.commit()
    return result


@router.get("/projects/{project_id}/approvals", response_model=list[ApprovalRequestWithStepsResponse])
def list_project_approvals(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List all approval requests for a project."""
    tid = current_tenant.id
    requests = db.query(ApprovalRequest).filter(ApprovalRequest.project_id == project_id, ApprovalRequest.tenant_id == tid).all()
    for r in requests:
        _enrich_steps(db, r, tid)
    return requests


@router.get("/approvals/{approval_id}", response_model=ApprovalRequestWithStepsResponse)
def get_approval_request(
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get an approval request with its steps."""
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id, ApprovalRequest.tenant_id == current_tenant.id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return _enrich_steps(db, request, current_tenant.id)


@router.post("/approvals/{approval_id}/steps/{step_id}/approve", response_model=ApprovalRequestWithStepsResponse)
def approve_step(
    approval_id: int,
    step_id: int,
    decision: ApprovalDecision = ApprovalDecision(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Approve a step in the approval chain. Advances to next step or completes."""
    tid = current_tenant.id
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id, ApprovalRequest.tenant_id == tid).first()
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if request.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Cannot approve: request is '{request.status}'")

    step = db.query(ApprovalStep).filter(ApprovalStep.id == step_id, ApprovalStep.request_id == approval_id, ApprovalStep.tenant_id == tid).first()
    if not step:
        raise HTTPException(status_code=404, detail="Approval step not found")
    if step.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Step is already '{step.status}'")
    if step.step_order != request.current_step:
        raise HTTPException(status_code=400, detail=f"This step is not the current step (current: step {request.current_step})")

    # Approve the step
    step.status = "Approved"
    step.comment = decision.comment
    step.approver_id = current_user.id
    from sqlalchemy.sql import func
    step.decided_at = func.now()

    # Check if this was the last step
    all_steps = db.query(ApprovalStep).filter(ApprovalStep.request_id == approval_id, ApprovalStep.tenant_id == tid).order_by(ApprovalStep.step_order).all()
    if step.step_order >= all_steps[-1].step_order:
        # Last step approved — request is fully approved
        request.status = "Approved"

        # AUTO-ADVANCE RELEASE
        if request.request_type == "release" and request.release_id and request.target_phase:
            from datetime import date as _date

            from app.models.release import Release
            from app.routers.releases import _create_phase_approval

            release = db.query(Release).filter(Release.id == request.release_id, Release.tenant_id == tid).first()
            if release and release.status != request.target_phase:
                release.status = request.target_phase
                if request.target_phase == "Released":
                    release.release_date = _date.today().isoformat()
                db.commit()
                db.refresh(release)

                # Auto-create the next phase's approval
                _create_phase_approval(db, release, current_user, tid)

        # Notify the PM (requested_by) that the approval was approved
        if request.requested_by:
            release_name = ""
            if request.release_id:
                from app.models.release import Release
                rel = db.query(Release).filter(Release.id == request.release_id, Release.tenant_id == tid).first()
                release_name = f"{rel.version} — {rel.name}" if rel else ""
            notify_approval_result(
                db, True, current_user.name, release_name,
                step.role_name, request.requested_by, request.project_id,
            )
        log_activity(db, current_user.id, current_user.name, request.project_id,
                     "approval", request.id, "approved",
                     f"Approved: {request.title} ({step.role_name})")
    else:
        # Advance to next step
        request.current_step = step.step_order + 1

    db.commit()
    db.refresh(request)
    return _enrich_steps(db, request, tid)


@router.post("/approvals/{approval_id}/steps/{step_id}/reject", response_model=ApprovalRequestWithStepsResponse)
def reject_step(
    approval_id: int,
    step_id: int,
    decision: ApprovalDecision = ApprovalDecision(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Reject a step. This rejects the entire approval request."""
    tid = current_tenant.id
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id, ApprovalRequest.tenant_id == tid).first()
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if request.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Cannot reject: request is '{request.status}'")

    step = db.query(ApprovalStep).filter(ApprovalStep.id == step_id, ApprovalStep.request_id == approval_id, ApprovalStep.tenant_id == tid).first()
    if not step:
        raise HTTPException(status_code=404, detail="Approval step not found")
    if step.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Step is already '{step.status}'")
    if step.step_order != request.current_step:
        raise HTTPException(status_code=400, detail=f"This step is not the current step (current: step {request.current_step})")

    step.status = "Rejected"
    step.comment = decision.comment
    step.approver_id = current_user.id
    from sqlalchemy.sql import func
    step.decided_at = func.now()

    request.status = "Rejected"

    # Notify the PM
    if request.requested_by:
        release_name = ""
        if request.release_id:
            from app.models.release import Release
            rel = db.query(Release).filter(Release.id == request.release_id, Release.tenant_id == tid).first()
            release_name = f"{rel.version} — {rel.name}" if rel else ""
        notify_approval_result(
            db, False, current_user.name, release_name,
            step.role_name, request.requested_by, request.project_id,
        )

    log_activity(db, current_user.id, current_user.name, request.project_id,
                 "approval", request.id, "rejected",
                 f"Rejected: {request.title} ({step.role_name})")

    db.commit()
    db.refresh(request)
    return _enrich_steps(db, request, tid)
