"""Schemas for comments."""
from pydantic import BaseModel


class CommentCreate(BaseModel):
    body: str
    task_id: int | None = None
    item_id: int | None = None


class CommentResponse(BaseModel):
    id: int
    task_id: int | None = None
    item_id: int | None = None
    user_id: int
    user_name: str | None = None
    body: str
    created_at: str | None = None
