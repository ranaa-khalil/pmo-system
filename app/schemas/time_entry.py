"""Schemas for time entries and timesheets."""
from datetime import date

from pydantic import BaseModel


class TimeEntryCreate(BaseModel):
    entry_date: date
    hours: float
    note: str | None = None
    item_id: int | None = None
    user_id: int | None = None  # defaults to the caller


class TimeEntryResponse(BaseModel):
    id: int
    project_id: int
    item_id: int | None = None
    user_id: int
    entry_date: date
    hours: float
    note: str | None = None
    created_by: int | None = None
    model_config = {"from_attributes": True}


class TimesheetLockRequest(BaseModel):
    user_id: int
    week_start: date


class TimeSummaryRow(BaseModel):
    user_id: int
    name: str | None = None
    total_hours: float
    week_hours: float
