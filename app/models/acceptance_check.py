"""AcceptanceCheck model — structured acceptance checks per backlog item.

The Bayan build-tracker parity layer: each Feature carries ordered checks
with a test result (Not tested | Pass | Fail). Results roll up to the
feature's progress (passed / total) shown in the feature tracker view.
"""
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base

CHECK_RESULTS = ["Not tested", "Pass", "Fail"]


class AcceptanceCheck(Base):
    __tablename__ = "acceptance_checks"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("backlog_items.id", ondelete="CASCADE"), nullable=False, index=True)

    check_order = Column(Integer, nullable=False, default=1)
    text = Column(String(500), nullable=False)
    result = Column(String(20), default="Not tested", nullable=False)

    created_at = Column(String, server_default=func.now(), nullable=False)
    updated_at = Column(String, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<AcceptanceCheck(id={self.id}, item={self.item_id}, order={self.check_order}, result={self.result})>"
