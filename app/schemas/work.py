"""Schemas for the unified Work list — the ONE Work view payload (GET /api/work).

Response model on the route so OpenAPI shows the real shape the Work view
board/timeline/list render from: the 10 R1 columns plus the 8 R2 columns
(item_type, epic, assigned_to_name, tags[], comment_count, board_order,
start_date, end_date) that make the Board lanes, tag chips, avatar stack
and Timeline bars possible.
"""
from datetime import date

from pydantic import BaseModel


class WorkItemTag(BaseModel):
    """One tag attached to a work item (the cross-tagging M2M)."""

    id: int
    name: str
    color: str | None = None


class WorkItem(BaseModel):
    """One row of the ONE Work view — every column the three projections need."""

    id: int
    title: str
    project_id: int | None = None
    project: str = ""
    phase: str | None = None
    status: str | None = None
    priority: str | None = None
    assigned_to: int | None = None
    assigned_to_name: str | None = None
    item_type: str | None = None
    epic: str | None = None
    tags: list[WorkItemTag] = []
    comment_count: int = 0
    board_order: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    target_release: str | None = None
    overdue: bool = False
    blocked: bool = False


class WorkList(BaseModel):
    """The unified cross-project work list."""

    items: list[WorkItem] = []
