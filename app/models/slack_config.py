"""SlackConfig model — tenant-level Slack digest integration (D4: second).

One config per tenant: an Incoming Webhook URL, an enabled flag, and the
digest time (HH:MM). The digest itself is built by app.services.slack_digest
and sent via plain HTTPS POST — no external dependency.
"""
from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class SlackConfig(Base):
    __tablename__ = "slack_configs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True, unique=True)

    webhook_url = Column(String(500), nullable=False)
    enabled = Column(Boolean, default=False, nullable=False)
    digest_time = Column(String(5), default="09:00", nullable=False)  # HH:MM
    last_sent_at = Column(String, nullable=True)

    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<SlackConfig(tenant={self.tenant_id}, enabled={self.enabled})>"
