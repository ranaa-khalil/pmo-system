"""Tenant models — multi-tenancy support for SaaS.

A Tenant is an organization (company) that uses the PMO system.
Users belong to tenants via TenantMembership (many-to-many).
Invitations allow tenant owners to invite new members.
"""
import secrets

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

# Plan tiers
PLAN_FREE = "free"
PLAN_TEAM = "team"
PLAN_BUSINESS = "business"
PLAN_ENTERPRISE = "enterprise"

PLAN_LIMITS = {
    PLAN_FREE: {"users": 3, "projects": 1},
    PLAN_TEAM: {"users": 25, "projects": 10},
    PLAN_BUSINESS: {"users": 100, "projects": 999999},
    PLAN_ENTERPRISE: {"users": 999999, "projects": 999999},
}

# Member roles within a tenant
MEMBER_ROLE_OWNER = "owner"
MEMBER_ROLE_ADMIN = "admin"
MEMBER_ROLE_MEMBER = "member"


class Tenant(Base):
    """An organization that uses the PMO system."""

    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    plan = Column(String(50), nullable=False, default=PLAN_FREE)
    status = Column(String(50), nullable=False, default="active")  # active, suspended, cancelled
    logo_url = Column(String(500), nullable=True)
    branding = Column(Text, nullable=True)  # JSON: {primary_color, custom_domain, hide_powered_by}
    settings = Column(Text, nullable=True)  # JSON blob for per-tenant config
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    memberships = relationship("TenantMembership", backref="tenant", cascade="all, delete-orphan")
    invitations = relationship("Invitation", backref="tenant", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Tenant(id={self.id}, name='{self.name}', plan='{self.plan}')>"


class TenantMembership(Base):
    """Associates a user with a tenant and their role within it."""

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), nullable=False, default=MEMBER_ROLE_MEMBER)
    joined_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", backref="memberships")

    def __repr__(self):
        return f"<TenantMembership(user_id={self.user_id}, tenant_id={self.tenant_id}, role='{self.role}')>"


class Invitation(Base):
    """A pending invitation for a user to join a tenant."""

    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default=MEMBER_ROLE_MEMBER)
    token = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")  # pending, accepted, expired, revoked
    invited_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<Invitation(tenant_id={self.tenant_id}, email='{self.email}', status='{self.status}')>"

    @staticmethod
    def generate_token() -> str:
        """Generate a secure random invitation token."""
        return secrets.token_urlsafe(32)
