"""Pydantic schemas for releases."""
from pydantic import BaseModel


class ReleaseCreate(BaseModel):
    version: str
    name: str
    description: str | None = None
    target_date: str | None = None
    milestone_id: int | None = None


class ReleaseUpdate(BaseModel):
    version: str | None = None
    name: str | None = None
    description: str | None = None
    status: str | None = None
    target_date: str | None = None
    release_date: str | None = None
    milestone_id: int | None = None


class ReleaseResponse(BaseModel):
    id: int
    project_id: int
    version: str
    name: str
    description: str | None = None
    status: str
    target_date: str | None = None
    release_date: str | None = None
    release_notes: str | None = None
    milestone_id: int | None = None
    created_by: int | None = None
    model_config = {"from_attributes": True}
