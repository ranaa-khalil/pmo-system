"""Pydantic schemas for the Project model."""
from datetime import date, datetime

from pydantic import BaseModel


class ProjectBase(BaseModel):
    name: str
    client_id: int
    description: str | None = None
    status: str | None = "Active"
    start_date: date | None = None
    github_repo: str | None = None
    version_prefix: str | None = None  # e.g. "1.0" — first release auto-numbers to 1.0.0
    dev_url: str | None = None
    uat_url: str | None = None
    prod_url: str | None = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    start_date: date | None = None
    github_repo: str | None = None
    version_prefix: str | None = None
    dev_url: str | None = None
    uat_url: str | None = None
    prod_url: str | None = None


class ProjectResponse(ProjectBase):
    id: int
    project_manager_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
