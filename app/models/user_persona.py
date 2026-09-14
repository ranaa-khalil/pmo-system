"""UserPersona model — personas used as primary actors in backlog items."""
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class UserPersona(Base):
    """A user persona for a project (e.g., 'Platform Admin', 'End Customer')."""

    __tablename__ = "user_personas"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)            # e.g. "Platform Admin"
    role = Column(String(100), nullable=True)             # e.g. "System Administrator"
    description = Column(Text, nullable=True)             # short description
    goals = Column(Text, nullable=True)                   # what this persona wants to achieve
    pain_points = Column(Text, nullable=True)             # challenges this persona faces
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<UserPersona(id={self.id}, name='{self.name}')>"
