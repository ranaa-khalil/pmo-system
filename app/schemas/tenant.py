"""Tenant schemas — request/response models for tenant management."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class TenantBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    logo_url: str | None = None


class TenantResponse(TenantBase):
    id: int
    plan: str
    status: str
    logo_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TenantMembershipResponse(BaseModel):
    id: int
    user_id: int
    tenant_id: int
    role: str
    joined_at: datetime
    user_email: str
    user_name: str

    model_config = {"from_attributes": True}


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = Field("member", pattern=r"^(owner|admin|member)$")


class AcceptInviteRequest(BaseModel):
    token: str
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=72)


class SwitchTenantRequest(BaseModel):
    tenant_id: int


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=72)
    tenant_name: str = Field(..., min_length=1, max_length=255)


class InvitationResponse(BaseModel):
    id: int
    tenant_id: int
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class UsageResponse(BaseModel):
    plan: str
    users: int
    users_limit: int
    projects: int
    projects_limit: int


class AdminCreateUserRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    role: str = Field("member", pattern=r"^(member|admin|owner)$")
