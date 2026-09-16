"""Pydantic schemas for forms."""
import json
from typing import Any

from pydantic import BaseModel, field_validator


def _parse_json(v):
    """Parse JSON strings to dict/list (for DB columns that may return strings)."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return {}
    return v


class FormTemplateResponse(BaseModel):
    id: int
    name: str
    form_type: str
    description: str | None = None
    field_schema: list[Any] = []
    model_config = {"from_attributes": True}

    @field_validator("field_schema", mode="before")
    @classmethod
    def parse_field_schema(cls, v):
        v = _parse_json(v)
        return v if isinstance(v, list) else []


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

    @field_validator("data", mode="before")
    @classmethod
    def parse_data(cls, v):
        v = _parse_json(v)
        return v if isinstance(v, dict) else {}


class FormInstanceWithTemplateResponse(FormInstanceResponse):
    template: FormTemplateResponse | None = None
