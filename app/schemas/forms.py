"""Pydantic schemas for forms."""
from typing import Any, Optional, List
from pydantic import BaseModel


class FormTemplateResponse(BaseModel):
    id: int
    name: str
    form_type: str
    description: Optional[str] = None
    field_schema: List[Any] = []
    model_config = {"from_attributes": True}


class FormInstanceCreate(BaseModel):
    template_id: int
    project_id: int
    backlog_item_id: Optional[int] = None


class FormInstanceUpdate(BaseModel):
    data: Optional[dict] = None


class FormInstanceResponse(BaseModel):
    id: int
    template_id: int
    project_id: int
    backlog_item_id: Optional[int] = None
    status: str
    data: dict = {}
    created_by: Optional[int] = None
    model_config = {"from_attributes": True}


class FormInstanceWithTemplateResponse(FormInstanceResponse):
    template: Optional[FormTemplateResponse] = None
