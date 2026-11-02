"""ShareLink model — public read-only view links (dashboard / project).

Tokenized links with expiry + optional password; revocable; view-counted.
Read-only by design: the public payload never includes members, settings,
or anything beyond the scoped aggregate.
"""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base

# Valid scopes
SHARE_SCOPES = ["dashboard", "project"]


class ShareLink(Base):
    """A public read-only view link."""

    __tablename__ = "share_links"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    scope = Column(String(50), nullable=False)  # "dashboard" | "project"
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    password_hash = Column(String(255), nullable=True)  # optional link password
    expires_at = Column(String, nullable=False)  # ISO timestamp
    revoked = Column(Boolean, default=False, nullable=False)
    view_count = Column(Integer, default=0, nullable=False)
    last_viewed_at = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ShareLink(id={self.id}, scope={self.scope!r}, token={self.token[:8]}...)>"
