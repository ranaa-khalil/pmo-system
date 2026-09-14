"""Pydantic schemas for UserPersona and ProjectTestAccount."""

from pydantic import BaseModel

# ===== User Persona =====

class PersonaBase(BaseModel):
    name: str
    role: str | None = None
    description: str | None = None
    goals: str | None = None
    pain_points: str | None = None


class PersonaCreate(PersonaBase):
    project_id: int


class PersonaUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    description: str | None = None
    goals: str | None = None
    pain_points: str | None = None


class PersonaResponse(PersonaBase):
    id: int
    project_id: int

    model_config = {"from_attributes": True}


# ===== Project Test Account =====

class TestAccountBase(BaseModel):
    environment: str  # Development, UAT, Production
    username: str
    password_hint: str | None = None
    role: str | None = None
    notes: str | None = None


class TestAccountCreate(TestAccountBase):
    project_id: int


class TestAccountUpdate(BaseModel):
    environment: str | None = None
    username: str | None = None
    password_hint: str | None = None
    role: str | None = None
    notes: str | None = None


class TestAccountResponse(TestAccountBase):
    id: int
    project_id: int

    model_config = {"from_attributes": True}
