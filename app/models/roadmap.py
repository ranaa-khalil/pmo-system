"""Roadmap model — a timeline view for a project (e.g., yearly)."""
from sqlalchemy import Column, Date, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class Roadmap(Base):
    """A roadmap with a timeline for a project."""

    __tablename__ = "roadmaps"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<Roadmap(id={self.id}, title={self.title})>"
