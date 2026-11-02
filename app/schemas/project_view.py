"""Schemas for saved project views."""
from pydantic import BaseModel


class ProjectViewCreate(BaseModel):
    name: str
    view_type: str = "board"
    filters: dict | list | str | None = None
    shared: bool = False


class ProjectViewResponse(BaseModel):
    id: int
    project_id: int
    name: str
    view_type: str
    filters: dict | list | str | None = None
    shared: bool
    created_by: int | None = None
    created_at: str | None = None
    model_config = {"from_attributes": True}
