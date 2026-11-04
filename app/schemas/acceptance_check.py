"""Schemas for acceptance checks."""
from pydantic import BaseModel


class AcceptanceCheckCreate(BaseModel):
    text: str
    check_order: int | None = None


class AcceptanceCheckUpdate(BaseModel):
    text: str | None = None
    result: str | None = None
    check_order: int | None = None


class AcceptanceCheckResponse(BaseModel):
    id: int
    item_id: int
    check_order: int
    text: str
    result: str
