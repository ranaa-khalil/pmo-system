"""Permission model — granular action permissions (e.g., 'client:create')."""
from sqlalchemy import Column, Integer, String, Text

from app.database import Base


class Permission(Base):
    """A granular permission that can be assigned to roles."""

    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Permission(id={self.id}, name={self.name})>"
