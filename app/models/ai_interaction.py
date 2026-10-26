"""AiInteraction model — audit trail for every AI read, proposal, intake, and report.

Feeds the trust metrics (proposal approval rate, sources clicked, verdict accuracy)
and gives every AI output a reviewable history.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base

# What kind of AI interaction this row records
AI_KINDS = ["query", "proposal", "intake", "brief", "report"]

# Lifecycle of a proposal / intake draft
AI_STATUSES = ["pending", "approved", "applied", "rejected", "expired"]


class AiInteraction(Base):
    """One AI interaction: grounded query, write proposal, intake draft, or brief."""

    __tablename__ = "ai_interactions"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    kind = Column(String(50), default="query", nullable=False)  # AI_KINDS
    question = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)
    sources = Column(Text, nullable=True)     # JSON list of {entity_type, entity_id, title}
    proposal = Column(Text, nullable=True)    # JSON: proposed operations / intake tree / brief
    status = Column(String(50), default="pending", nullable=False)  # AI_STATUSES
    outcome = Column(Text, nullable=True)     # JSON: result of confirm/apply (created ids, errors)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<AiInteraction(id={self.id}, kind={self.kind}, status={self.status})>"
