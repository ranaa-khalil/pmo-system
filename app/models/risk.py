"""Risk model — a register row per project, replacing P1's risk drafts.

A risk carries severity/probability (score = severity × probability on the
5×5 scale), status (Open → Mitigating → Closed), an owner, and a source
(manual | copilot | evidence) so every risk traces to its origin. Score is
computed in Python (never stored stale); unknown strings score 0.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

# 5×5 scale: score = severity_level × probability_level
SEVERITY_LEVELS = {"Low": 1, "Medium": 2, "High": 3, "Critical": 5}
PROBABILITY_LEVELS = {"Rare": 1, "Unlikely": 2, "Medium": 3, "Possible": 3, "Likely": 4, "Almost Certain": 5}

RISK_STATUSES = ["Open", "Mitigating", "Closed"]
RISK_SOURCES = ["manual", "copilot", "evidence"]


class Risk(Base):
    __tablename__ = "risks"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    release_id = Column(Integer, nullable=True)  # optional: risk tied to a release

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    mitigation = Column(Text, nullable=True)

    severity = Column(String(20), default="Medium", nullable=False)      # Low|Medium|High|Critical
    probability = Column(String(20), default="Possible", nullable=False)  # Rare..Almost Certain
    status = Column(String(20), default="Open", nullable=False)           # Open|Mitigating|Closed

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    source = Column(String(20), default="manual", nullable=False)  # manual|copilot|evidence

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    project = relationship("Project", foreign_keys=[project_id], viewonly=True)
    owner = relationship("User", foreign_keys=[owner_id], viewonly=True)

    @property
    def score(self) -> int:
        """Risk score = severity × probability (0 when unknown strings)."""
        s = SEVERITY_LEVELS.get(self.severity, 0)
        p = PROBABILITY_LEVELS.get(self.probability, 0)
        return s * p
