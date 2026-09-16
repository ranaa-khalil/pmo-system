"""Plan model — configurable subscription plans for tenants.

Each Plan defines resource limits (max_users, max_projects, etc.).
Tenants are assigned to a Plan via Tenant.plan_id (FK).
When a plan is assigned or updated, limits are propagated to tenant.limits.
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, Boolean
from sqlalchemy.sql import func

from app.database import Base


class Plan(Base):
    """A subscription plan that defines resource limits for tenants."""

    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    max_users = Column(Integer, nullable=False, default=999999)
    max_projects = Column(Integer, nullable=False, default=999999)
    max_releases = Column(Integer, nullable=False, default=999999)
    max_backlog_items = Column(Integer, nullable=False, default=999999)
    price_monthly = Column(Integer, nullable=False, default=0)  # in SAR
    price_yearly = Column(Integer, nullable=False, default=0)   # in SAR
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description or "",
            "max_users": self.max_users,
            "max_projects": self.max_projects,
            "max_releases": self.max_releases,
            "max_backlog_items": self.max_backlog_items,
            "price_monthly": self.price_monthly,
            "price_yearly": self.price_yearly,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
