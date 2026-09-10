"""Pydantic schemas for backlog items."""
from typing import Optional, List
from pydantic import BaseModel


class BacklogItemBrief(BaseModel):
    """Minimal info about a backlog item, used for dependency display."""
    id: int
    title: str
    current_phase: str
    status: str
    model_config = {"from_attributes": True}


class BacklogItemBase(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "Medium"
    kpi_id: Optional[int] = None
    epic: Optional[str] = None
    item_type: Optional[str] = None
    primary_actor: Optional[str] = None
    story_points: Optional[int] = None
    target_release: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    dependencies: Optional[str] = None


class BacklogItemCreate(BacklogItemBase):
    project_id: int


class BacklogItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    current_phase: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[int] = None
    kpi_id: Optional[int] = None
    epic: Optional[str] = None
    item_type: Optional[str] = None
    primary_actor: Optional[str] = None
    story_points: Optional[int] = None
    target_release: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    dependencies: Optional[str] = None


class BacklogItemResponse(BacklogItemBase):
    id: int
    project_id: int
    current_phase: str
    status: str
    github_issue_number: Optional[int] = None
    github_synced_at: Optional[str] = None
    github_issue_url: Optional[str] = None
    assigned_to: Optional[int] = None
    depends_on: List[BacklogItemBrief] = []
    blocked_by: List[BacklogItemBrief] = []
    model_config = {"from_attributes": True}


class DependencyAdd(BaseModel):
    """Add a dependency: this item depends on the specified item."""
    depends_on_id: int
