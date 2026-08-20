"""Pydantic schemas for approval workflow."""
from typing import Optional, List
from pydantic import BaseModel


class ApprovalStepCreate(BaseModel):
    role_name: str
    step_order: int
    approver_id: Optional[int] = None


class ApprovalStepResponse(BaseModel):
    id: int
    request_id: int
    step_order: int
    role_name: str
    approver_id: Optional[int] = None
    status: str
    comment: Optional[str] = None
    decided_at: Optional[str] = None
    model_config = {"from_attributes": True}


class ApprovalRequestCreate(BaseModel):
    project_id: int
    title: str
    description: Optional[str] = None
    request_type: str
    release_id: Optional[int] = None
    target_phase: Optional[str] = None
    steps: List[ApprovalStepCreate]


class ApprovalDecision(BaseModel):
    comment: Optional[str] = None


class ApprovalRequestResponse(BaseModel):
    id: int
    project_id: int
    title: str
    description: Optional[str] = None
    request_type: str
    requested_by: Optional[int] = None
    status: str
    current_step: int
    release_id: Optional[int] = None
    target_phase: Optional[str] = None
    model_config = {"from_attributes": True}


class ApprovalRequestWithStepsResponse(ApprovalRequestResponse):
    steps: List[ApprovalStepResponse] = []
