"""Stakeholder model — a person involved in a project.

Stakeholders can be internal (Obelion staff) or external (client, partner).
Each stakeholder has a RACI role on the project.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Stakeholder(Base):
    """A stakeholder on a project — linked to a RACI role."""

    __tablename__ = "stakeholders"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    company = Column(String(255), nullable=True)
    role_name = Column(String(100), nullable=False)  # e.g., "Product Owner", "QA Lead"
    # Seeded and API-provided values may use full labels such as "Accountable".
    raci_type = Column(String(20), nullable=False, default="I")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    project = relationship("Project", backref="stakeholders")

    def __repr__(self):
        return f"<Stakeholder(id={self.id}, name='{self.name}', role='{self.role_name}', project_id={self.project_id})>"
