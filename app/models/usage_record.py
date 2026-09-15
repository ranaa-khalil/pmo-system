"""Usage tracking model — per-tenant usage records over time.

Tracks metrics like active users, projects, releases, etc.
Used for quota enforcement and billing reporting.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# Metric types
METRIC_USERS = "users"
METRIC_PROJECTS = "projects"
METRIC_RELEASES = "releases"
METRIC_BACKLOG_ITEMS = "backlog_items"
METRIC_API_CALLS = "api_calls"


class UsageRecord(Base):
    """A daily usage snapshot for a tenant.

    One record per tenant per day per metric.
    Used for trend analysis and billing reporting.
    """

    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "metric", "date", name="uq_tenant_metric_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    metric = Column(String(50), nullable=False)  # users, projects, releases, etc.
    count = Column(Integer, nullable=False, default=0)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD format
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    tenant = relationship("Tenant", backref="usage_records")

    def __repr__(self):
        return f"<UsageRecord(tenant_id={self.tenant_id}, metric='{self.metric}', count={self.count}, date='{self.date}')>"
