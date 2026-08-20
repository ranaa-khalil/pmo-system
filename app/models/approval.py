"""Approval workflow models — RACI gate approval chains.

When a release, backlog item, or form needs approval, an ApprovalRequest is
created with a chain of ApprovalSteps. Each step represents a RACI role that
must approve before the request can proceed.

The 12 RACI roles from Release Process V2.0:
Product Owner, PM, Tech Lead, Dev Lead, Developer, QA Lead, QA Engineer,
DevOps Lead, DevOps Engineer, Security Officer, Release Manager, Stakeholder
"""
from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


# Valid request types
REQUEST_TYPES = ["release", "hotfix", "rollback", "backlog_advance", "form_signoff"]

# Valid statuses
APPROVAL_STATUSES = ["Pending", "Approved", "Rejected", "Skipped"]


class ApprovalRequest(Base):
    """A request that goes through a multi-step RACI approval chain."""

    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    request_type = Column(String(100), nullable=False)
    requested_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="Pending", nullable=False)
    current_step = Column(Integer, default=1, nullable=False)
    created_at = Column(String, server_default=func.now(), nullable=False)
    updated_at = Column(String, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ApprovalRequest(id={self.id}, title={self.title}, status={self.status})>"


class ApprovalStep(Base):
    """A single step in an approval chain, tied to a RACI role."""

    __tablename__ = "approval_steps"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False)
    step_order = Column(Integer, nullable=False)
    role_name = Column(String(100), nullable=False)
    approver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="Pending", nullable=False)
    comment = Column(Text, nullable=True)
    decided_at = Column(String, nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ApprovalStep(id={self.id}, order={self.step_order}, role={self.role_name}, status={self.status})>"
