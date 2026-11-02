"""Comment model — threaded comments on tasks and backlog items.

One table serves both targets: exactly one of task_id / item_id is set.
Author + timestamp render under the body (Wrike parity); body is plain
text with markdown rendering left to the frontend.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("user_tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    item_id = Column(Integer, ForeignKey("backlog_items.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    body = Column(Text, nullable=False)
    created_at = Column(String, server_default=func.now(), nullable=False)

    author = relationship("User", foreign_keys=[user_id], viewonly=True)

    def __repr__(self):
        return f"<Comment(id={self.id}, task={self.task_id}, item={self.item_id}, user={self.user_id})>"
