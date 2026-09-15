"""ProjectVision model — one-to-one with Project."""
from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class ProjectVision(Base):
    """The strategic vision for a project (one per project)."""

    __tablename__ = "project_visions"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_vision_per_project"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    statement = Column(Text, nullable=False)
    strategic_objectives = Column(Text, nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)
    updated_at = Column(String, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ProjectVision(id={self.id}, project_id={self.project_id})>"
