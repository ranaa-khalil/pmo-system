"""Pydantic schemas for user tasks (personal to-dos)."""
from datetime import date

from pydantic import BaseModel


class UserTaskBase(BaseModel):
    title: str
    description: str | None = None
    project_id: int | None = None
    milestone_id: int | None = None
    due_date: date | None = None
    reminder_days: int = 3
    priority: str = "Medium"


class UserTaskCreate(UserTaskBase):
    assigned_to: int | None = None  # defaults to current user
    status: str = "Pending"


class UserTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    project_id: int | None = None
    milestone_id: int | None = None
    due_date: date | None = None
    reminder_days: int | None = None
    status: str | None = None
    priority: str | None = None


class UserTaskResponse(UserTaskBase):
    id: int
    assigned_to: int
    created_by: int | None = None
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    # Joined fields for display
    project_name: str | None = None
    milestone_title: str | None = None
    assignee_name: str | None = None
    model_config = {"from_attributes": True}
