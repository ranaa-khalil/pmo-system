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

    # Load steps for response
    request.steps = db.query(ApprovalStep).filter(ApprovalStep.request_id == request.id).order_by(ApprovalStep.step_order).all()
    return request


@router.get("/projects/{project_id}/approvals", response_model=List[ApprovalRequestWithStepsResponse])
def list_project_approvals(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all approval requests for a project."""
    requests = db.query(ApprovalRequest).filter(ApprovalRequest.project_id == project_id).all()
    for r in requests:
        r.steps = db.query(ApprovalStep).filter(ApprovalStep.request_id == r.id).order_by(ApprovalStep.step_order).all()
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
    request.steps = db.query(ApprovalStep).filter(ApprovalStep.request_id == request.id).order_by(ApprovalStep.step_order).all()
    return request


@router.post("/approvals/{approval_id}/steps/{step_id}/approve", response_model=ApprovalRequestWithStepsResponse)
def approve_step(
    approval_id: int,
    step_id: int,
    decision: ApprovalDecision = ApprovalDecision(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve a step in the approval chain. Advances to next step or completes."""
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
    else:
        # Advance to next step
        request.current_step = step.step_order + 1

    db.commit()
    db.refresh(request)
    request.steps = all_steps
    return request


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
    request.steps = db.query(ApprovalStep).filter(ApprovalStep.request_id == approval_id).order_by(ApprovalStep.step_order).all()
    return request


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
