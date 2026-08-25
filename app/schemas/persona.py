"""Pydantic schemas for UserPersona and ProjectTestAccount."""
from typing import Optional
from pydantic import BaseModel


# ===== User Persona =====

class PersonaBase(BaseModel):
    name: str
    role: Optional[str] = None
    description: Optional[str] = None
    goals: Optional[str] = None
    pain_points: Optional[str] = None


class PersonaCreate(PersonaBase):
    project_id: int


class PersonaUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    description: Optional[str] = None
    goals: Optional[str] = None
    pain_points: Optional[str] = None


class PersonaResponse(PersonaBase):
    id: int
    project_id: int

    model_config = {"from_attributes": True}


# ===== Project Test Account =====

class TestAccountBase(BaseModel):
    environment: str  # Development, UAT, Production
    username: str
    password_hint: Optional[str] = None
    role: Optional[str] = None
    notes: Optional[str] = None


class TestAccountCreate(TestAccountBase):
    project_id: int


class TestAccountUpdate(BaseModel):
    environment: Optional[str] = None
    username: Optional[str] = None
    password_hint: Optional[str] = None
    role: Optional[str] = None
    notes: Optional[str] = None


class TestAccountResponse(TestAccountBase):
    id: int
    project_id: int

    model_config = {"from_attributes": True}
