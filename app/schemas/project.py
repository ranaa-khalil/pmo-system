"""Pydantic schemas for the Project model."""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class ProjectBase(BaseModel):
    name: str
    client_id: int
    description: Optional[str] = None
    status: Optional[str] = "Active"
    start_date: Optional[date] = None
    github_repo: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    github_repo: Optional[str] = None


class ProjectResponse(ProjectBase):
    id: int
    project_manager_id: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}
