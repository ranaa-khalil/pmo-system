"""Pydantic schemas for releases."""
from typing import Optional, List
from pydantic import BaseModel


class ReleaseCreate(BaseModel):
    version: str
    name: str
    description: Optional[str] = None
    target_date: Optional[str] = None
    milestone_id: Optional[int] = None


class ReleaseUpdate(BaseModel):
    version: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    target_date: Optional[str] = None
    release_date: Optional[str] = None
    milestone_id: Optional[int] = None


class ReleaseResponse(BaseModel):
    id: int
    project_id: int
    version: str
    name: str
    description: Optional[str] = None
    status: str
    target_date: Optional[str] = None
    release_date: Optional[str] = None
    release_notes: Optional[str] = None
    milestone_id: Optional[int] = None
    created_by: Optional[int] = None
    model_config = {"from_attributes": True}
