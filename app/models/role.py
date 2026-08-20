"""Role model — based on the 12 RACI roles from RACI Matrix v2.3."""
from sqlalchemy import Column, Integer, String, Text
from app.database import Base


class Role(Base):
    """A role in the RACI matrix (e.g., Product Manager, Tech Lead, QA Lead)."""

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Role(id={self.id}, name='{self.name}')>"
