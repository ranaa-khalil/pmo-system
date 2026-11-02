"""Guest approval link models — tokenized links for external approvers.

A guest link shares one approval request (optionally bound to a specific RACI
step) with an outside stakeholder: no login, token in the URL, optional
password, hard expiry, revoke support. Guest decisions are recorded verbatim.
"""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class ApprovalGuestLink(Base):
    """A tokenized share link for one approval request."""

    __tablename__ = "approval_guest_links"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    request_id = Column(Integer, ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    # Optional binding: the guest decision approves/rejects this RACI step
    step_id = Column(Integer, ForeignKey("approval_steps.id", ondelete="CASCADE"), nullable=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    label = Column(String(200), nullable=True)  # guest name / org shown in the UI
    password_hash = Column(String(255), nullable=True)  # optional link password
    expires_at = Column(String, nullable=False)  # ISO timestamp
    revoked = Column(Boolean, default=False, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ApprovalGuestLink(id={self.id}, request={self.request_id}, label={self.label!r})>"


class ApprovalGuestDecision(Base):
    """A decision recorded through a guest link (verbatim audit row)."""

    __tablename__ = "approval_guest_decisions"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    link_id = Column(Integer, ForeignKey("approval_guest_links.id", ondelete="CASCADE"), nullable=False)
    request_id = Column(Integer, ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    decision = Column(String(50), nullable=False)  # "Approved" | "Rejected"
    comment = Column(Text, nullable=True)
    guest_name = Column(String(200), nullable=True)
    decided_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ApprovalGuestDecision(id={self.id}, request={self.request_id}, decision={self.decision!r})>"
