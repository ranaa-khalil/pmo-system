"""FormTemplate and FormInstance models — automated form generation.

Templates are based on the Obelion Release Process V2.0:
- Deployment Checklist
- UAT Sign-off
- Hotfix Request
- RCA (Root Cause Analysis)
- Retrospective
"""
from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base

# Valid form types
FORM_TYPES = [
    "deployment_checklist",
    "uat_signoff",
    "hotfix_request",
    "rca",
    "retrospective",
    "release_notes",
    "rollback_runbook",
]

# Valid statuses for a form instance
FORM_STATUSES = ["Draft", "Submitted", "Approved", "Rejected"]


class FormTemplate(Base):
    """A reusable form template with a JSON field schema."""

    __tablename__ = "form_templates"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    form_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    field_schema = Column(JSON, nullable=False, default=list)
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<FormTemplate(id={self.id}, name={self.name}, type={self.form_type})>"


class FormInstance(Base):
    """A filled-in instance of a form template, linked to a project."""

    __tablename__ = "form_instances"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    template_id = Column(Integer, ForeignKey("form_templates.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    backlog_item_id = Column(Integer, ForeignKey("backlog_items.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="Draft", nullable=False)
    data = Column(JSON, nullable=False, default=dict)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)
    updated_at = Column(String, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<FormInstance(id={self.id}, template_id={self.template_id}, status={self.status})>"
