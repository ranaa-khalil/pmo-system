"""Activity Log model — audit trail for all entity changes."""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class ActivityLog(Base):
    """Immutable audit trail entry for any entity change."""

    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # nullable for system actions
    user_name = Column(String(255), nullable=True)  # denormalized for quick display
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    entity_type = Column(String(50), nullable=False, index=True)  # backlog_item, release, kpi, milestone, task, client, project, approval
    entity_id = Column(Integer, nullable=False, index=True)
    action = Column(String(50), nullable=False)  # created, updated, deleted, advanced, approved, rejected, assigned, signed_off
    summary = Column(String(500), nullable=False)  # human-readable: "Advanced 'Login API' to Testing"
    changes = Column(Text, nullable=True)  # JSON of field-level diffs: {"field": {"old": x, "new": y}}
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")
    project = relationship("Project")
