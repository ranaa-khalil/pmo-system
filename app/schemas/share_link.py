"""Pydantic schemas for public share links."""
from pydantic import BaseModel


class ShareLinkCreate(BaseModel):
    scope: str  # "dashboard" | "project"
    project_id: int | None = None
    password: str | None = None
    expires_in_days: int = 30


class ShareUnlock(BaseModel):
    password: str | None = None


class ShareLinkResponse(BaseModel):
    id: int
    token: str
    scope: str
    project_id: int | None = None
    has_password: bool
    expires_at: str
    revoked: bool
    view_count: int
    url: str
    model_config = {"from_attributes": True}
