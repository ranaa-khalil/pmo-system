"""Pydantic schemas for guest approval links."""
from pydantic import BaseModel


class GuestLinkCreate(BaseModel):
    step_id: int | None = None  # bind the guest decision to a RACI step
    label: str | None = None
    password: str | None = None  # optional link password
    expires_in_days: int = 7  # default 7 days


class GuestDecisionCreate(BaseModel):
    decision: str  # "Approved" | "Rejected"
    comment: str | None = None
    guest_name: str | None = None
    password: str | None = None


class GuestLinkResponse(BaseModel):
    id: int
    request_id: int
    step_id: int | None = None
    token: str
    label: str | None = None
    has_password: bool
    expires_at: str
    revoked: bool
    url: str
    model_config = {"from_attributes": True}
