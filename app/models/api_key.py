"""API Key model — for programmatic API access without JWT.

API keys are tenant-scoped and can have restricted scopes.
The key itself is hashed (SHA-256) before storage — only the full key
is shown once at creation time.
"""
import hashlib
import secrets

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# Available scopes
SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPE_ADMIN = "admin"

ALL_SCOPES = [SCOPE_READ, SCOPE_WRITE, SCOPE_ADMIN]

# Prefix for PMO API keys (so they're identifiable)
KEY_PREFIX = "pmo_"


class ApiKey(Base):
    """A per-tenant API key for programmatic access."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)  # Human-readable label
    key_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hash
    key_prefix = Column(String(12), nullable=False)  # First 8 chars for identification
    scopes = Column(String(200), nullable=False, default="read")  # Comma-separated: read,write,admin
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    tenant = relationship("Tenant", backref="api_keys")

    def __repr__(self):
        return f"<ApiKey(id={self.id}, name='{self.name}', tenant_id={self.tenant_id})>"

    @staticmethod
    def generate_key() -> str:
        """Generate a new API key. Returns the full key (only shown once)."""
        raw = secrets.token_urlsafe(32)
        return f"{KEY_PREFIX}{raw}"

    @staticmethod
    def hash_key(key: str) -> str:
        """Hash an API key for storage."""
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def get_prefix(key: str) -> str:
        """Get the display prefix of a key (first 8 chars + ...)."""
        if len(key) <= 12:
            return key
        return key[:8] + "..."

    def has_scope(self, scope: str) -> bool:
        """Check if this key has the given scope."""
        return scope in (self.scopes or "").split(",")
