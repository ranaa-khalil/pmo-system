"""Schemas for the ItemType vocabulary + ItemProof proofing."""
from pydantic import BaseModel, Field


class ItemTypeCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=50)
    label: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    color: str = Field("blue", max_length=20)
    sort_order: int = 0


class ItemTypeUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    color: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class ItemTypeResponse(BaseModel):
    id: int
    key: str
    label: str
    description: str | None
    color: str
    is_active: bool
    sort_order: int


class ProofDecide(BaseModel):
    decision: str  # Approved | Changes Requested
    comment: str | None = None
