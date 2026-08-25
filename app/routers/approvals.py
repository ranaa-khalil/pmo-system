"""Approval workflow API router — RACI gate approval chains."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.approval import ApprovalRequest, ApprovalStep
from app.schemas.approval import (
    ApprovalRequestCreate,
    ApprovalRequestResponse,
    ApprovalRequestWithStepsResponse,
    ApprovalStepResponse,
    ApprovalDecision,
)

router = APIRouter(prefix="/api", tags=["approvals"])


def _enrich_steps(db: Session, request: ApprovalRequest):
    """Add approver_name to each step by resolving the FK."""
    steps = db.query(ApprovalStep).filter(
        ApprovalStep.request_id == request.id
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
):
    """Create an approval request with a chain of RACI steps."""
    if not db.query(Project).filter(Project.id == project_id).first():
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
        )
        db.add(step)
    db.commit()
    db.refresh(request)

    # Load steps for response (with approver names)
    return _enrich_steps(db, request)


@router.get("/projects/{project_id}/approvals", response_model=List[ApprovalRequestWithStepsResponse])
def list_project_approvals(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all approval requests for a project."""
    requests = db.query(ApprovalRequest).filter(ApprovalRequest.project_id == project_id).all()
    for r in requests:
        _enrich_steps(db, r)
    return requests


@router.get("/approvals/{approval_id}", response_model=ApprovalRequestWithStepsResponse)
def get_approval_request(
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get an approval request with its steps."""
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return _enrich_steps(db, request)


@router.post("/approvals/{approval_id}/steps/{step_id}/approve", response_model=ApprovalRequestWithStepsResponse)
def approve_step(
    approval_id: int,
    step_id: int,
    decision: ApprovalDecision = ApprovalDecision(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve a step in the approval chain. Advances to next step or completes.

    If this is a release phase-gate approval and this is the last step, the
    release is auto-advanced to the target phase and the next phase's approval
    is auto-created.
    """
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if request.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Cannot approve: request is '{request.status}'")

    step = db.query(ApprovalStep).filter(ApprovalStep.id == step_id, ApprovalStep.request_id == approval_id).first()
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
    all_steps = db.query(ApprovalStep).filter(ApprovalStep.request_id == approval_id).order_by(ApprovalStep.step_order).all()
    if step.step_order >= all_steps[-1].step_order:
        # Last step approved — request is fully approved
        request.status = "Approved"

        # ── AUTO-ADVANCE RELEASE ───────────────────────────────────────────
        # If this is a release phase-gate approval, advance the release to
        # the target phase and create the next phase's approval.
        if request.request_type == "release" and request.release_id and request.target_phase:
            from app.models.release import Release
            from app.routers.releases import V_CYCLE, PHASE_GATE_ROLES, _create_phase_approval
            from datetime import date as _date

            release = db.query(Release).filter(Release.id == request.release_id).first()
            if release and release.status != request.target_phase:
                release.status = request.target_phase
                if request.target_phase == "Released":
                    release.release_date = _date.today().isoformat()
                db.commit()
                db.refresh(release)

                # Auto-create the next phase's approval
                _create_phase_approval(db, release, current_user)
    else:
        # Advance to next step
        request.current_step = step.step_order + 1

    db.commit()
    db.refresh(request)
    return _enrich_steps(db, request)


@router.post("/approvals/{approval_id}/steps/{step_id}/reject", response_model=ApprovalRequestWithStepsResponse)
def reject_step(
    approval_id: int,
    step_id: int,
    decision: ApprovalDecision = ApprovalDecision(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject a step. This rejects the entire approval request."""
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if request.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Cannot reject: request is '{request.status}'")

    step = db.query(ApprovalStep).filter(ApprovalStep.id == step_id, ApprovalStep.request_id == approval_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="Approval step not found")
    if step.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Step is already '{step.status}'")

    step.status = "Rejected"
    step.comment = decision.comment
    step.approver_id = current_user.id
    from sqlalchemy.sql import func
    step.decided_at = func.now()

    # Reject the entire request
    request.status = "Rejected"

    db.commit()
    db.refresh(request)
    return _enrich_steps(db, request)


@router.delete("/approvals/{approval_id}", status_code=204)
def delete_approval_request(
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an approval request and all its steps."""
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    db.delete(request)
    db.commit()
