"""Pydantic schemas for stakeholders and roles."""
from typing import Optional, List
from pydantic import BaseModel


# ===== Stakeholder =====
class StakeholderCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    role_name: str
    raci_type: str = "I"
    notes: Optional[str] = None


class StakeholderUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    role_name: Optional[str] = None
    raci_type: Optional[str] = None
    notes: Optional[str] = None


class StakeholderResponse(BaseModel):
    id: int
    project_id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    role_name: str
    raci_type: str
    notes: Optional[str] = None
    model_config = {"from_attributes": True}


# ===== Role =====
class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class RoleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
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
