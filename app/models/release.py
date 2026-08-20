"""Release model — groups backlog items into a versioned release.

A release goes through the V-cycle:
  Planning → In Progress → Testing → UAT → Pre-Release → Released → Post-Release

Each release links to backlog items and can generate release notes.
"""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


# Valid release statuses (maps to the V-cycle phases)
RELEASE_STATUSES = [
    "Planning",      # Gathering requirements, selecting items
    "In Progress",   # Design + Development
    "Testing",       # SIT
    "UAT",           # User acceptance testing
    "Pre-Release",   # Ready to deploy, generating release notes
    "Released",      # Deployed to production
    "Post-Release",  # Monitoring, hotfixes if needed
    "Cancelled",     # Abandoned
]


class Release(Base):
    """A versioned release that groups backlog items through the V-cycle."""

    __tablename__ = "releases"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    version = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="Planning", nullable=False)
    target_date = Column(String(50), nullable=True)
    release_date = Column(String(50), nullable=True)
    release_notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    project = relationship("Project", backref="releases")
    items = relationship("ReleaseItem", backref="release", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Release(id={self.id}, version={self.version}, status={self.status})>"


class ReleaseItem(Base):
    """Links a backlog item to a release (many-to-many)."""

    __tablename__ = "release_items"
    __table_args__ = (
        UniqueConstraint("release_id", "backlog_item_id", name="uq_release_backlog"),
    )

    id = Column(Integer, primary_key=True, index=True)
    release_id = Column(Integer, ForeignKey("releases.id", ondelete="CASCADE"), nullable=False)
    backlog_item_id = Column(Integer, ForeignKey("backlog_items.id", ondelete="CASCADE"), nullable=False)

    # Relationship
    backlog_item = relationship("BacklogItem", backref="release_links")

    def __repr__(self):
        return f"<ReleaseItem(release_id={self.release_id}, backlog_item_id={self.backlog_item_id})>"
