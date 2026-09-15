"""GitHubBoardConfig model — per-project GitHub board configuration.

Stores which GitHub repo and (optionally) which GitHub Project V2 board
the PMO system should export approved backlog items to.

When auto_export is enabled, backlog items are automatically exported to
GitHub (issue created + added to project board) when they reach the
configured export trigger phase.
"""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class GitHubBoardConfig(Base):
    """Per-project GitHub board configuration for exporting approved features."""

    __tablename__ = "github_board_configs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Target repo in "owner/repo" format (e.g. "opexsa/cloudgate")
    # Falls back to project.github_repo if empty
    repo = Column(String(255), nullable=True)

    # GitHub Project V2 node ID (GraphQL global node ID, e.g. "PVT_xxxx")
    # When set, exported issues are also added to this project board
    project_node_id = Column(String(100), nullable=True)

    # Human-readable project title (cached for display without API calls)
    project_title = Column(String(255), nullable=True)

    # Full URL to the GitHub Project V2 board (e.g. https://github.com/users/ranaa-khalil/projects/1)
    project_url = Column(String(500), nullable=True)

    # Comma-separated default labels to apply to exported issues
    # e.g. "from-pmo,feature,enhancement"
    default_labels = Column(String(500), nullable=True, default="from-pmo")

    # When True, items are automatically exported when they reach the trigger phase
    auto_export = Column(Boolean, default=False, nullable=False)

    # Which phase triggers the auto-export (default: "Development")
    # Items are exported when they enter this phase
    export_trigger_phase = Column(String(50), default="Development", nullable=False)

    # Optional prefix for GitHub issue titles (e.g. "[CG]" for CloudGate)
    issue_title_prefix = Column(String(20), nullable=True)

    # Include acceptance criteria in the issue body
    include_acceptance_criteria = Column(Boolean, default=True, nullable=False)

    # Include dependencies info in the issue body
    include_dependencies = Column(Boolean, default=True, nullable=False)

    created_at = Column(String, server_default=func.now(), nullable=False)
    updated_at = Column(String, server_default=func.now(), onupdate=func.now())

    # Relationship
    project = relationship("Project", backref="github_board_config")

    def __repr__(self):
        return f"<GitHubBoardConfig(project_id={self.project_id}, repo={self.repo}, auto_export={self.auto_export})>"
