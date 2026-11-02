"""ItemType model — tenant-scoped item-type vocabulary.

D6 (map) of the Wrike inclusion plan: a tenant-scoped info table over the
standardized vocabulary. New tenants are seeded with the defaults; admins can
add custom types with labels and colors. backlog_items.item_type stores the
key.
"""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base

# Standardized vocabulary — seeded per tenant, extendable by admins
DEFAULT_ITEM_TYPES = [
    {"key": "Feature", "label": "Feature", "color": "blue"},
    {"key": "Bug", "label": "Bug", "color": "rose"},
    {"key": "Enhancement", "label": "Enhancement", "color": "amber"},
    {"key": "Epic", "label": "Epic", "color": "violet"},
    {"key": "Chore", "label": "Chore", "color": "ink"},
]

# Tailwind chip classes shared with the UI
ITEM_TYPE_COLORS = {
    "blue": "bg-blue-50 text-blue-600",
    "rose": "bg-rose-50 text-rose-600",
    "amber": "bg-amber-50 text-amber-600",
    "violet": "bg-violet-50 text-violet-600",
    "ink": "bg-ink-100 text-ink-500",
    "emerald": "bg-emerald-50 text-emerald-600",
    "indigo": "bg-indigo-50 text-indigo-600",
}


class ItemType(Base):
    """One item type in a tenant's vocabulary."""

    __tablename__ = "item_types"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(50), nullable=False, index=True)
    label = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    color = Column(String(20), default="blue", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(String, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ItemType(id={self.id}, key={self.key}, tenant={self.tenant_id})>"
