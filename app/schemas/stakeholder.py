"""Pydantic schemas for stakeholders and roles."""
from pydantic import BaseModel


# ===== Stakeholder =====
class StakeholderCreate(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    role_name: str
    raci_type: str = "I"
    notes: str | None = None


class StakeholderUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    role_name: str | None = None
    raci_type: str | None = None
    notes: str | None = None


class StakeholderResponse(BaseModel):
    id: int
    project_id: int
    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    role_name: str
    raci_type: str
    notes: str | None = None
    model_config = {"from_attributes": True}


# ===== Role =====
class RoleCreate(BaseModel):
    name: str
    description: str | None = None


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class RoleResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    model_config = {"from_attributes": True}


# ===== Role Assignment =====
class RoleAssignmentCreate(BaseModel):
    user_id: int
    role_id: int
    project_id: int


class RoleAssignmentResponse(BaseModel):
    id: int
    user_id: int
    role_id: int
    project_id: int
    model_config = {"from_attributes": True}
