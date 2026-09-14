"""KPI model — key performance indicators for a project."""
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class KPI(Base):
    """A key performance indicator for a project."""

    __tablename__ = "kpis"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    target_value = Column(String(255), nullable=True)
    current_value = Column(String(255), nullable=True)
    unit = Column(String(50), nullable=True)
    category = Column(String(100), nullable=True)
    vision_objective = Column(String(500), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<KPI(id={self.id}, name={self.name}, project_id={self.project_id})>"
