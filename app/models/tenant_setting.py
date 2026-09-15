"""Tenant settings model — per-tenant configuration key-value store.

Stores per-tenant settings like GitHub token, AI API key, etc.
Secrets are encrypted at rest using the Fernet symmetric encryption.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# Setting keys
SETTING_GITHUB_TOKEN = "github_token"
SETTING_AI_API_KEY = "ai_api_key"
SETTING_AI_BASE_URL = "ai_base_url"
SETTING_AI_MODEL = "ai_model"

# Settings that contain secrets (encrypted at rest)
SECRET_KEYS = {SETTING_GITHUB_TOKEN, SETTING_AI_API_KEY}


class TenantSetting(Base):
    """A per-tenant configuration setting (key-value pair).

    Secret values are encrypted at rest using Fernet symmetric encryption.
    Non-secret values are stored as plaintext.
    """

    __tablename__ = "tenant_settings"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    value = Column(Text, nullable=True)  # encrypted for secrets, plaintext otherwise
    is_secret = Column(Integer, default=0)  # 1 if the value is encrypted
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant", backref="tenant_settings")

    def __repr__(self):
        return f"<TenantSetting(tenant_id={self.tenant_id}, key='{self.key}')>"
