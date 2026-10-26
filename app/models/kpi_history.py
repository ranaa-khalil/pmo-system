"""KpiHistory model — a timestamped snapshot of a KPI's current_value.

Written whenever a KPI's value changes (API update, copilot advance). Gives
the kpi_trend analytics and the predictive flags a real history instead of a
single current number. Score-bearing columns stay String like the KPI model —
values may be "99.7", "40", or "n/a"; numeric parsing happens at read time.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class KpiHistory(Base):
    """One historical value of a KPI, recorded when the value changed."""

    __tablename__ = "kpi_history"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    kpi_id = Column(Integer, ForeignKey("kpis.id", ondelete="CASCADE"), nullable=False, index=True)

    value = Column(String(255), nullable=False)      # snapshot of current_value
    source = Column(String(20), default="manual", nullable=False)  # manual|copilot|api

    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<KpiHistory(id={self.id}, kpi_id={self.kpi_id}, value={self.value})>"
