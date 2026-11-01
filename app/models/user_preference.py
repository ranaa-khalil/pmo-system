"""UserPreference model — per-user UI layout persistence (widget order, view modes).

One row per user per key; the value is a JSON string. Keys are allow-listed
in the preferences router so the surface stays predictable.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class UserPreference(Base):
    """A per-user UI preference (e.g. dashboard widget order)."""

    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_preferences_user_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    value = Column(Text, nullable=True)  # JSON string
    updated_at = Column(String, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<UserPreference(user={self.user_id}, key={self.key!r})>"
