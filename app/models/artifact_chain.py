"""ArtifactChain model — hash-chained audit trail entries."""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class ArtifactChain(Base):
    """One immutable, hash-linked entry in an entity's audit trail.

    prev_hash + hash make the chain tamper-evident: verifying re-walks every
    link and recomputes each hash. payload is a JSON snapshot of the change.
    """

    __tablename__ = "artifact_chain"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    entity_type = Column(String(50), nullable=False, index=True)  # approval_request, backlog_item, lifecycle_template, project
    entity_id = Column(Integer, nullable=False, index=True)
    seq = Column(Integer, nullable=False)  # per-entity monotonic sequence
    action = Column(String(50), nullable=False)  # created, approved, rejected, advanced, drafted, updated
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name = Column(String(255), nullable=True)  # denormalized for display
    artifact_type = Column(String(50), nullable=False, default="state_change")  # state_change | ai_draft | gate_event
    payload = Column(JSON, nullable=True)  # snapshot: {field diffs, status, evidence refs}
    prev_hash = Column(String(64), nullable=False)
    hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ArtifactChain(id={self.id}, entity={self.entity_type}#{self.entity_id}, seq={self.seq}, action={self.action})>"
