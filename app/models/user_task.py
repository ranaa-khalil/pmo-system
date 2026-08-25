"""UserTask model — a personal to-do item, optionally linked to a project and milestone."""
from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey
from sqlalchemy.sql import func
from app.database import Base

# Valid statuses for a user task
TASK_STATUSES = ["Pending", "In Progress", "Completed", "Cancelled"]

# Valid priorities
TASK_PRIORITIES = ["Low", "Medium", "High", "Urgent"]


class UserTask(Base):
    """A personal to-do item for a user.

    Can be:
    - General (no project/milestone link)
    - Linked to a project only
    - Linked to a project + specific milestone
    """

    __tablename__ = "user_tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    assigned_to = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    milestone_id = Column(Integer, ForeignKey("milestones.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(Date, nullable=True)
    reminder_days = Column(Integer, default=3, nullable=False)  # remind N days before due_date
    status = Column(String(50), default="Pending", nullable=False)
    priority = Column(String(50), default="Medium", nullable=False)
    created_at = Column(String, server_default=func.now(), nullable=False)
    updated_at = Column(String, server_default=func.now(), onupdate=func.now())
    completed_at = Column(String, nullable=True)

    def __repr__(self):
        return f"<UserTask(id={self.id}, title={self.title[:30]}, status={self.status})>"
