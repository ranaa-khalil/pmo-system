"""Pydantic schemas for GitHub board configuration and sync."""

from pydantic import BaseModel


class GitHubProjectInfo(BaseModel):
    """Info about a GitHub Project V2 board (from GraphQL API)."""
    id: str
    title: str
    number: int | None = None
    url: str = ""
    description: str | None = ""
    closed: bool = False


class GitHubBoardConfigBase(BaseModel):
    """Base schema for GitHub board configuration."""
    repo: str | None = None
    project_node_id: str | None = None
    project_title: str | None = None
    project_url: str | None = None
    default_labels: str | None = "from-pmo"
    auto_export: bool = False
    export_trigger_phase: str = "Development"
    issue_title_prefix: str | None = None
    include_acceptance_criteria: bool = True
    include_dependencies: bool = True


class GitHubBoardConfigCreate(GitHubBoardConfigBase):
    project_id: int


class GitHubBoardConfigUpdate(BaseModel):
    """Update schema — all fields optional."""
    repo: str | None = None
    project_node_id: str | None = None
    project_title: str | None = None
    project_url: str | None = None
    default_labels: str | None = None
    auto_export: bool | None = None
    export_trigger_phase: str | None = None
    issue_title_prefix: str | None = None
    include_acceptance_criteria: bool | None = None
    include_dependencies: bool | None = None


class GitHubBoardConfigResponse(GitHubBoardConfigBase):
    id: int
    project_id: int
    model_config = {"from_attributes": True}


class GitHubExportRequest(BaseModel):
    """Request to export specific backlog items to GitHub."""
    item_ids: list[int] = []  # specific items to export; empty = export all approved/ready


class GitHubResolveBoardRequest(BaseModel):
    """Request to resolve a GitHub Project V2 board URL."""
    url: str


class GitHubExportResult(BaseModel):
    """Result of exporting items to GitHub."""
    total: int = 0
    exported: int = 0
    skipped: int = 0  # already synced
    failed: int = 0
    details: list[dict] = []  # per-item results


class GitHubSyncStatus(BaseModel):
    """Sync status for a project's backlog items."""
    total_items: int = 0
    synced_items: int = 0
    unsynced_items: int = 0
    config: GitHubBoardConfigResponse | None = None


class GitHubImportResult(BaseModel):
    """Result of importing status from GitHub back to PMO."""
    total: int = 0          # total synced items checked
    updated: int = 0        # items whose status changed
    unchanged: int = 0      # items whose status stayed the same
    failed: int = 0         # items that couldn't be fetched
    closed_count: int = 0   # items found closed on GitHub
    open_count: int = 0     # items found open on GitHub
    details: list[dict] = []  # per-item results
