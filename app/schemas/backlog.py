"""Pydantic schemas for backlog items."""
from typing import Optional
from pydantic import BaseModel


class BacklogItemBase(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "Medium"


class BacklogItemCreate(BacklogItemBase):
    project_id: int


class BacklogItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    current_phase: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[int] = None


class BacklogItemResponse(BacklogItemBase):
    id: int
    project_id: int
    current_phase: str
    status: str
    github_issue_number: Optional[int] = None
    assigned_to: Optional[int] = None
    model_config = {"from_attributes": True}
