"""ItemProof model — versioned deliverable proofs on backlog items.

Wrike-style proofing: upload a deliverable (image/PDF), reviewers approve or
request changes. One proof row per version; the latest version's status is
the item's proof status.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base

# Proof statuses
PROOF_STATUSES = ["Pending", "Approved", "Changes Requested"]


class ItemProof(Base):
    """One version of a deliverable attached to a backlog item."""

    __tablename__ = "item_proofs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("backlog_items.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    title = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=True)   # /uploads/proofs/...
    file_url = Column(String(500), nullable=True)    # external link (alternative)
    status = Column(String(30), default="Pending", nullable=False, index=True)  # PROOF_STATUSES
    uploaded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploader_name = Column(String(255), nullable=True)
    decided_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decider_name = Column(String(255), nullable=True)
    decision_comment = Column(Text, nullable=True)
    decided_at = Column(String, nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ItemProof(id={self.id}, item={self.item_id}, v{self.version}, {self.status})>"
