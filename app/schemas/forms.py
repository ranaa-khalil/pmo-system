"""Pydantic schemas for forms."""
from typing import Any

from pydantic import BaseModel


class FormTemplateResponse(BaseModel):
    id: int
    name: str
    form_type: str
    description: str | None = None
    field_schema: list[Any] = []
    model_config = {"from_attributes": True}


class FormInstanceCreate(BaseModel):
    template_id: int
    project_id: int
    backlog_item_id: int | None = None


class FormInstanceUpdate(BaseModel):
    data: dict | None = None


class FormInstanceResponse(BaseModel):
    id: int
    template_id: int
    project_id: int
    backlog_item_id: int | None = None
    status: str
    data: dict = {}
    created_by: int | None = None
    model_config = {"from_attributes": True}


class FormInstanceWithTemplateResponse(FormInstanceResponse):
    template: FormTemplateResponse | None = None
