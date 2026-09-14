"""Pydantic schemas for approval workflow."""

from pydantic import BaseModel


class ApprovalStepCreate(BaseModel):
    role_name: str
    step_order: int
    approver_id: int | None = None


class ApprovalStepResponse(BaseModel):
    id: int
    request_id: int
    step_order: int
    role_name: str
    approver_id: int | None = None
    approver_name: str | None = None
    status: str
    comment: str | None = None
    decided_at: str | None = None
    model_config = {"from_attributes": True}


class ApprovalRequestCreate(BaseModel):
    project_id: int
    title: str
    description: str | None = None
    request_type: str
    release_id: int | None = None
    target_phase: str | None = None
    steps: list[ApprovalStepCreate]


class ApprovalDecision(BaseModel):
    comment: str | None = None


class ApprovalRequestResponse(BaseModel):
    id: int
    project_id: int
    title: str
    description: str | None = None
    request_type: str
    requested_by: int | None = None
    status: str
    current_step: int
    release_id: int | None = None
    target_phase: str | None = None
    model_config = {"from_attributes": True}


class ApprovalRequestWithStepsResponse(ApprovalRequestResponse):
    steps: list[ApprovalStepResponse] = []
