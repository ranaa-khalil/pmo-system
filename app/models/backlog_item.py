"""BacklogItem model — a business requirement following the 9-phase release process."""
from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


# The 9 phases of the release process, in order
PHASES = [
    "Requirements",
    "Design",
    "Development",
    "Testing",
    "UAT",
    "Pre-Release",
    "Release",
    "Post-Release",
    "Retrospective",
]

# Valid statuses for a backlog item
STATUSES = ["Draft", "In Progress", "Blocked", "Done", "Cancelled"]

# Valid priorities
PRIORITIES = ["Low", "Medium", "High", "Critical"]


class BacklogItem(Base):
    """A business requirement / backlog item that flows through the 9-phase process."""

    __tablename__ = "backlog_items"

    id = Column(Integer, primary_key=True, index=True)
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
    dependencies = Column(Text, nullable=True)
    github_issue_number = Column(Integer, nullable=True)
    assigned_to = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kpi_id = Column(Integer, ForeignKey("kpis.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)
    updated_at = Column(String, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<BacklogItem(id={self.id}, title={self.title[:30]}, phase={self.current_phase})>"
