"""User model — a person who uses the PMO system."""
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    """A user of the PMO system (Obelion staff or client stakeholder)."""

    __tablename__ = "users"
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    system_role = Column(String(50), default="member", nullable=False)  # kept for backward compat
    is_active = Column(Boolean, default=True, nullable=False)
    active_tenant_id = Column(Integer, nullable=True)  # which tenant the user is currently working in
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}')>"
