"""ProjectTestAccount model — test accounts that stakeholders can use per environment."""
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class ProjectTestAccount(Base):
    """A test account for a project environment (e.g., UAT admin credentials)."""

    __tablename__ = "project_test_accounts"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    environment = Column(String(50), nullable=False)      # "Development", "UAT", "Production"
    username = Column(String(200), nullable=False)        # e.g. "admin@pnu-cloud.opex.com.sa"
    password_hint = Column(String(200), nullable=True)    # e.g. "Admin@2026" (stored as hint, not secure)
    role = Column(String(100), nullable=True)             # e.g. "Super Admin", "Account Manager"
    notes = Column(Text, nullable=True)                   # any extra info
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ProjectTestAccount(id={self.id}, env='{self.environment}', user='{self.username}')>"
