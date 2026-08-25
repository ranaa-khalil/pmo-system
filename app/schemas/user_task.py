"""Pydantic schemas for user tasks (personal to-dos)."""
from typing import Optional
from datetime import date
from pydantic import BaseModel


class UserTaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    project_id: Optional[int] = None
    milestone_id: Optional[int] = None
    due_date: Optional[date] = None
    reminder_days: int = 3
    priority: str = "Medium"


class UserTaskCreate(UserTaskBase):
    assigned_to: Optional[int] = None  # defaults to current user
    status: str = "Pending"


class UserTaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[int] = None
    milestone_id: Optional[int] = None
    due_date: Optional[date] = None
    reminder_days: Optional[int] = None
    status: Optional[str] = None
    priority: Optional[str] = None


class UserTaskResponse(UserTaskBase):
    id: int
    assigned_to: int
    created_by: Optional[int] = None
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    # Joined fields for display
    project_name: Optional[str] = None
    milestone_title: Optional[str] = None
    assignee_name: Optional[str] = None
    model_config = {"from_attributes": True}
