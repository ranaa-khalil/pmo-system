"""TenantLifecycleTemplate model — tenant-defined lifecycles (P4.4).

Methodology depth: tenants define custom lifecycle templates for edge
project types. template_for() prefers the tenant's template for the
project_type key and falls back to the built-in vocabularies.
"""
from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class TenantLifecycleTemplate(Base):
    """A tenant's custom lifecycle for a project_type key."""

    __tablename__ = "lifecycle_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_type", name="uq_lifecycle_per_tenant_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    project_type = Column(String(50), nullable=False, index=True)  # the key it overrides
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    item_phases = Column(JSON, nullable=False)       # ["Requirements", ...]
    release_stages = Column(JSON, nullable=False)    # ["UAT", ...]
    gate_deliverables = Column(JSON, nullable=False) # {phase: [deliverables]}
    gate_roles = Column(JSON, nullable=False)        # {phase: role_name}
    fields = Column(JSON, nullable=False, default=list)  # custom fields [{name, label, type, options}]
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)
    updated_at = Column(String, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TenantLifecycleTemplate(id={self.id}, tenant_id={self.tenant_id}, type={self.project_type})>"
