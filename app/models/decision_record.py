"""DecisionRecord — R3: decisions of any call, one place, searchable, chained.

A decision is a first-class artifact: a gate sign-off, a manual call, or an
AI-intake decision all live here — searchable across title/decision/rationale
and chained to the work (project, backlog item, approval request). A decision
that supersedes or extends another carries chained_from_id lineage and marks
the old one superseded. Every create/supersede appends a hash-linked
artifact_chain entry (entity_type="decision") so the trail is tamper-evident.

KPI hook (plan v1 R3): decision latency is measured from these rows —
made_at vs the linked approval request's timeline; no second place to look.
"""
from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base

# Where a decision came from — the gate decisions and AI intake can cite records later
SOURCES = ["manual", "gate", "ai"]

# Lifecycle: active until something supersedes it
STATUSES = ["active", "superseded"]


class DecisionRecord(Base):
    """One decision: what was decided, why, what else was considered, and how it chains."""

    __tablename__ = "decision_records"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    # Any call can be projectless — decisions are not forced under a project
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    title = Column(String(255), nullable=False)
    decision = Column(Text, nullable=False)  # what was decided
    rationale = Column(Text, nullable=True)  # why
    alternatives = Column(Text, nullable=True)  # what else was considered
    made_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    made_at = Column(String, server_default=func.now(), nullable=False)  # immutable after create
    source = Column(String(20), nullable=False, default="manual")  # manual | gate | ai
    # Chained to the work
    item_id = Column(Integer, ForeignKey("backlog_items.id", ondelete="SET NULL"), nullable=True)
    approval_request_id = Column(
        Integer, ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True
    )  # gate decisions link here
    # A decision that supersedes/extends another
    chained_from_id = Column(
        Integer, ForeignKey("decision_records.id", ondelete="SET NULL"), nullable=True
    )
    status = Column(String(20), nullable=False, default="active")  # active | superseded

    # Rethink v2 Phase A: decisions-by-project + newest-first (the composite the
    # migration a7c2e9f41d05 creates for existing databases).
    __table_args__ = (Index("ix_decision_records_project_created", "project_id", "made_at"),)

    def __repr__(self):
        return f"<DecisionRecord(id={self.id}, title={self.title[:30]}, status={self.status})>"
