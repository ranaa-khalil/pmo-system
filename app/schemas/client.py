"""Pydantic schemas for the Client model."""
from datetime import datetime

from pydantic import BaseModel, EmailStr


class ClientBase(BaseModel):
    name: str
    contact_name: str | None = None
    contact_email: EmailStr | None = None
    description: str | None = None


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: str | None = None
    contact_name: str | None = None
    contact_email: EmailStr | None = None
    description: str | None = None


class ClientResponse(ClientBase):
    id: int
    account_manager_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
