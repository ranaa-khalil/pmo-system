"""ProjectView model — a saved backlog view per project (GitHub Boards parity).

A saved view captures a name, the layout it applies to (board), and its
filters as a JSON string (search, phase, status, group_by). Views marked
shared are visible to everyone with project access; private views only to
their creator. Filters are stored verbatim as JSON — the frontend applies
them to the loaded backlog items.
"""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base

VIEW_TYPES = ["board"]


class ProjectView(Base):
    __tablename__ = "project_views"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    name = Column(String(200), nullable=False)
    view_type = Column(String(20), default="board", nullable=False)
    filters = Column(Text, nullable=True)  # JSON string: {search, phase, status, group_by}
    shared = Column(Boolean, default=False, nullable=False)

    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ProjectView(id={self.id}, name={self.name!r}, project={self.project_id})>"
