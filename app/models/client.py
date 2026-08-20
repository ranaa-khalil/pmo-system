"""Client model — represents a client organization (e.g., NITC/PNU, GO Telecom)."""
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Client(Base):
    """A client organization that OPEX serves."""

    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("contact_email", name="uq_client_email"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    contact_name = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    account_manager_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<Client(id={self.id}, name='{self.name}')>"
