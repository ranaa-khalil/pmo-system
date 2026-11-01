"""Tag model — tenant-wide tag pool with cross-entity links (cross-tagging).

One task/item can carry many tags without duplication; the pool is
tenant-scoped so analytics stay comparable across projects. Colors come from
a fixed palette so chips stay on the brand grid.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Table, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

# M2M links: one tag on many items, one item carrying many tags — no
# duplication of the item itself (Wrike-style cross-tagging).
backlog_item_tags = Table(
    "backlog_item_tags",
    Base.metadata,
    Column(
        "backlog_item_id",
        Integer,
        ForeignKey("backlog_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

user_task_tags = Table(
    "user_task_tags",
    Base.metadata,
    Column(
        "user_task_id",
        Integer,
        ForeignKey("user_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

# Fixed chip palette (frontend maps these to Tailwind classes)
TAG_COLORS = ["indigo", "violet", "blue", "emerald", "amber", "rose", "slate"]


class Tag(Base):
    """A tenant-scoped tag in the workspace-wide pool."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tags_tenant_name"),)

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    color = Column(String(30), default="indigo", nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)

    items = relationship("BacklogItem", secondary=backlog_item_tags, backref="tags")
    tasks = relationship("UserTask", secondary=user_task_tags, backref="tags")

    def __repr__(self):
        return f"<Tag(id={self.id}, name={self.name!r}, tenant={self.tenant_id})>"
