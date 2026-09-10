"""Pydantic schemas for GitHub board configuration and sync."""
from typing import Optional, List
from pydantic import BaseModel


class GitHubProjectInfo(BaseModel):
    """Info about a GitHub Project V2 board (from GraphQL API)."""
    id: str
    title: str
    number: Optional[int] = None
    url: str = ""
    description: str = ""
    closed: bool = False


class GitHubBoardConfigBase(BaseModel):
    """Base schema for GitHub board configuration."""
    repo: Optional[str] = None
    project_node_id: Optional[str] = None
    project_title: Optional[str] = None
    default_labels: Optional[str] = "from-pmo"
    auto_export: bool = False
    export_trigger_phase: str = "Development"
    issue_title_prefix: Optional[str] = None
    include_acceptance_criteria: bool = True
    include_dependencies: bool = True


class GitHubBoardConfigCreate(GitHubBoardConfigBase):
    project_id: int


class GitHubBoardConfigUpdate(BaseModel):
    """Update schema — all fields optional."""
    repo: Optional[str] = None
    project_node_id: Optional[str] = None
    project_title: Optional[str] = None
    default_labels: Optional[str] = None
    auto_export: Optional[bool] = None
    export_trigger_phase: Optional[str] = None
    issue_title_prefix: Optional[str] = None
    include_acceptance_criteria: Optional[bool] = None
    include_dependencies: Optional[bool] = None


class GitHubBoardConfigResponse(GitHubBoardConfigBase):
    id: int
    project_id: int
    model_config = {"from_attributes": True}


class GitHubExportRequest(BaseModel):
    """Request to export specific backlog items to GitHub."""
    item_ids: List[int] = []  # specific items to export; empty = export all approved/ready


class GitHubExportResult(BaseModel):
    """Result of exporting items to GitHub."""
    total: int = 0
    exported: int = 0
    skipped: int = 0  # already synced
    failed: int = 0
    details: List[dict] = []  # per-item results


class GitHubSyncStatus(BaseModel):
    """Sync status for a project's backlog items."""
    total_items: int = 0
    synced_items: int = 0
    unsynced_items: int = 0
    config: Optional[GitHubBoardConfigResponse] = None
