"""Engagement — R4: the contract wrapper around one client's projects.

A client engagement is the umbrella a consultant's work ships under: the
contract dates, the contract value (a currency-agnostic string — never a
float), a lifecycle status (active | paused | closed), and the PMO lead who
owns the relationship. A client can hold several engagements; each engagement
wraps that client's projects — the read-side rollup on GET /api/engagements/{id}
proves the engagement → its projects direction (the consultant's unit of work
is "client → its projects").

Every create/delete appends a hash-linked artifact_chain entry
(entity_type="engagement") via the reports-router pattern, so the trail is
tamper-evident.
"""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base

# Lifecycle: an engagement runs until the contract closes
STATUSES = ["active", "paused", "closed"]


class Engagement(Base):
    """One client engagement: the contract wrapper around its projects."""

    __tablename__ = "engagements"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    # The client this engagement bills — NOT NULL: an engagement is always for a client
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="active")  # active | paused | closed
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    # Currency-agnostic string ("SAR 250,000", "USD 80k") — never a float
    contract_value = Column(String(50), nullable=True)
    # The PMO lead who owns the relationship
    pmo_lead_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Engagement(id={self.id}, name='{self.name}', status={self.status})>"
