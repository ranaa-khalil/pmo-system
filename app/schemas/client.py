"""Pydantic schemas for the Client model."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class ClientBase(BaseModel):
    name: str
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    description: Optional[str] = None


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    description: Optional[str] = None


class ClientResponse(ClientBase):
    id: int
    account_manager_id: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}
