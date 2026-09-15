"""Notification model — in-app and email notifications."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Notification(Base):
    """A notification sent to a user (in-app and/or email)."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # approval_request, task_due, task_overdue, release_advanced, item_sent_back, phase_changed, mention
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    link = Column(String(500), nullable=True)  # route to navigate to when clicked
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", backref="notifications")


class NotificationPreference(Base):
    """Per-user notification preferences."""

    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    email_enabled = Column(Boolean, default=True, nullable=False)
    in_app_enabled = Column(Boolean, default=True, nullable=False)
    approval_requests = Column(Boolean, default=True, nullable=False)
    task_reminders = Column(Boolean, default=True, nullable=False)
    release_updates = Column(Boolean, default=True, nullable=False)
    daily_digest = Column(Boolean, default=False, nullable=False)
    digest_time = Column(String(5), default="09:00", nullable=False)  # HH:MM

    user = relationship("User", backref="notification_pref", uselist=False)
