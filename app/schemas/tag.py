"""Pydantic schemas for tags (cross-tagging pool)."""
from pydantic import BaseModel


class TagCreate(BaseModel):
    name: str
    color: str = "indigo"


class TagAttach(BaseModel):
    tag_id: int


class TagResponse(BaseModel):
    id: int
    name: str
    color: str
    created_at: str | None = None
    # Usage counts for the picker
    item_count: int = 0
    task_count: int = 0
    model_config = {"from_attributes": True}
