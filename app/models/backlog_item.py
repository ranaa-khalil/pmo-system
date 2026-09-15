"""BacklogItem model — a business requirement following the 9-phase release process."""
from sqlalchemy import Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

# The 9 phases of the release process, in order
# Phases that individual backlog items go through (item-level)
ITEM_PHASES = [
    "Requirements",
    "Design",
    "Development",
    "Testing",
    "Ready for UAT",
]

# Phases that happen at the release level (after items are bundled)
RELEASE_PHASES = [
    "UAT",
    "Pre-Release",
    "Release",
    "Post-Release",
    "Retrospective",
]

# Full 9-phase process (for reference / display)
PHASES = ITEM_PHASES + RELEASE_PHASES

# Valid statuses for a backlog item
STATUSES = ["Draft", "In Progress", "Blocked", "Done", "Cancelled"]

# Valid priorities
PRIORITIES = ["Low", "Medium", "High", "Critical"]

# Association table for self-referential many-to-many dependencies
# A row (dependent_id, depends_on_id) means: item `dependent_id` depends on item `depends_on_id`
backlog_dependencies = Table(
    "backlog_dependencies",
    Base.metadata,
    Column("dependent_id", Integer, ForeignKey("backlog_items.id", ondelete="CASCADE"), primary_key=True),
    Column("depends_on_id", Integer, ForeignKey("backlog_items.id", ondelete="CASCADE"), primary_key=True),
)


class BacklogItem(Base):
    """A business requirement / backlog item that flows through the 9-phase process."""

    __tablename__ = "backlog_items"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    current_phase = Column(String(50), default="Requirements", nullable=False)
    status = Column(String(50), default="Draft", nullable=False)
    priority = Column(String(50), default="Medium", nullable=False)
    # Extended fields from Master Backlog
    epic = Column(String(200), nullable=True)
    item_type = Column(String(50), nullable=True)  # Feature, Bug, Enhancement, etc.
    primary_actor = Column(String(100), nullable=True)  # End Customer, Platform Admin, etc.
    story_points = Column(Integer, nullable=True)
    target_release = Column(String(50), nullable=True)  # e.g. "2026-08"
    acceptance_criteria = Column(Text, nullable=True)
    dependencies = Column(Text, nullable=True)  # legacy free-text field (kept for backward compat)
    github_issue_number = Column(Integer, nullable=True)
    github_synced_at = Column(String, nullable=True)  # ISO timestamp of last GitHub export
    github_issue_url = Column(String(500), nullable=True)  # full URL to the GitHub issue
    # Reverse-sync fields (GitHub → PMO)
    github_state = Column(String(20), nullable=True)  # 'open' or 'closed'
    github_labels = Column(String(500), nullable=True)  # comma-separated labels from GitHub
    github_assignees = Column(String(500), nullable=True)  # comma-separated assignee logins
    github_last_sync_at = Column(String, nullable=True)  # ISO timestamp of last import from GitHub
    assigned_to = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kpi_id = Column(Integer, ForeignKey("kpis.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)
    updated_at = Column(String, server_default=func.now(), onupdate=func.now())

    # Self-referential many-to-many: this item depends on these items
    depends_on = relationship(
        "BacklogItem",
        secondary=backlog_dependencies,
        primaryjoin=(id == backlog_dependencies.c.dependent_id),
        secondaryjoin=(id == backlog_dependencies.c.depends_on_id),
        backref="blocked_by",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<BacklogItem(id={self.id}, title={self.title[:30]}, phase={self.current_phase})>"
