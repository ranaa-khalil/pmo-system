"""Pydantic schemas for backlog items."""

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
    description: str | None = None
    priority: str = "Medium"
    kpi_id: int | None = None
    epic: str | None = None
    item_type: str | None = None
    primary_actor: str | None = None
    story_points: int | None = None
    target_release: str | None = None
    acceptance_criteria: str | None = None
    dependencies: str | None = None


class BacklogItemCreate(BacklogItemBase):
    project_id: int


class BacklogItemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    current_phase: str | None = None
    status: str | None = None
    priority: str | None = None
    assigned_to: int | None = None
    kpi_id: int | None = None
    epic: str | None = None
    item_type: str | None = None
    primary_actor: str | None = None
    story_points: int | None = None
    target_release: str | None = None
    acceptance_criteria: str | None = None
    dependencies: str | None = None


class BacklogItemResponse(BacklogItemBase):
    id: int
    project_id: int
    current_phase: str
    status: str
    github_issue_number: int | None = None
    github_synced_at: str | None = None
    github_issue_url: str | None = None
    github_state: str | None = None
    github_labels: str | None = None
    github_assignees: str | None = None
    github_last_sync_at: str | None = None
    assigned_to: int | None = None
    depends_on: list[BacklogItemBrief] = []
    blocked_by: list[BacklogItemBrief] = []
    model_config = {"from_attributes": True}


class DependencyAdd(BaseModel):
    """Add a dependency: this item depends on the specified item."""
    depends_on_id: int
