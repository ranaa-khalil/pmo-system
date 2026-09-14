"""Project model — a project for a client (e.g., PNU Cloud, CloudGate)."""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Project(Base):
    """A project belonging to a client."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="Active")
    start_date = Column(Date, nullable=True)
    github_repo = Column(String(255), nullable=True)
    version_prefix = Column(String(20), nullable=True)  # e.g. "1.0" → releases auto-number 1.0.0, 1.1.0, 1.2.0
    project_manager_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Environment URLs
    dev_url = Column(String(500), nullable=True)      # e.g. https://dev.pnu-cloud.opex.com.sa
    uat_url = Column(String(500), nullable=True)      # e.g. https://uat.pnu-cloud.opex.com.sa
    prod_url = Column(String(500), nullable=True)     # e.g. https://pnu-cloud.opex.com.sa

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    client = relationship("Client", backref="projects")
    personas = relationship("UserPersona", backref="project", cascade="all, delete-orphan", order_by="UserPersona.name")
    test_accounts = relationship("ProjectTestAccount", backref="project", cascade="all, delete-orphan", order_by="ProjectTestAccount.environment")

    def __repr__(self):
        return f"<Project(id={self.id}, name='{self.name}')>"
