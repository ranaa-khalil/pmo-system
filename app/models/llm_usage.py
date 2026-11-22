"""LlmUsage model — one row per LLM call (ADR: the LLM resilience layer).

Auditability for every AI call: feature, ok/fallback, latency. Tenant LLM
key VALUES are never recorded here (or anywhere) — only the call's shape.
"""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class LlmUsage(Base):
    """One LLM call: feature, ok/fallback, latency."""

    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    feature = Column(String(50), nullable=False, index=True)  # ai | intake | brief | copilot | evidence
    ok = Column(Boolean, nullable=False, default=True)
    latency_ms = Column(Integer, nullable=False, default=0)
    error = Column(String(200), nullable=True)  # fallback reason — never key values
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<LlmUsage(feature={self.feature}, ok={self.ok}, latency_ms={self.latency_ms})>"
