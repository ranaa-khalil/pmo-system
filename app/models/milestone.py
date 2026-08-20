"""Milestone model — a point in time within a roadmap."""
from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class Milestone(Base):
    """A milestone within a roadmap."""

    __tablename__ = "milestones"

    id = Column(Integer, primary_key=True, index=True)
    roadmap_id = Column(Integer, ForeignKey("roadmaps.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    target_date = Column(Date, nullable=True)
    status = Column(String(50), default="On Track", nullable=False)
    description = Column(String(500), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<Milestone(id={self.id}, title={self.title})>"
