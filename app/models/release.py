"""Release model — groups backlog items into a versioned release.

The release stage ladder is DATA per project type, resolved by
app.services.lifecycle.release_lifecycle (the software family walks the
7-phase V-cycle; other ladders come from the template's release_stages).

Each release links to backlog items and can generate release notes.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Release(Base):
    """A versioned release that groups backlog items through the V-cycle."""

    __tablename__ = "releases"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    version = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="Planning", nullable=False)
    target_date = Column(String(50), nullable=True)
    release_date = Column(String(50), nullable=True)
    release_notes = Column(Text, nullable=True)
    milestone_id = Column(Integer, ForeignKey("milestones.id", ondelete="SET NULL"), nullable=True)
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
    tenant_id = Column(Integer, nullable=True, index=True)
    release_id = Column(Integer, ForeignKey("releases.id", ondelete="CASCADE"), nullable=False, index=True)
    backlog_item_id = Column(Integer, ForeignKey("backlog_items.id", ondelete="CASCADE"), nullable=False)

    # Relationship
    backlog_item = relationship("BacklogItem", backref="release_links")

    def __repr__(self):
        return f"<ReleaseItem(release_id={self.release_id}, backlog_item_id={self.backlog_item_id})>"
