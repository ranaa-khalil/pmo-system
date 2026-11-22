"""BeatRun model — persisted record of an officer beat execution.

ADR-02: the beat is idempotent via the (job, window_key) unique constraint —
a window runs at most once per job no matter how many times the process
restarts (catch-up-on-start) or how many replicas boot (they also take the
Postgres advisory lock before iterating tenants).
"""
from sqlalchemy import JSON, Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class BeatRun(Base):
    """One execution of a scheduled beat (job + window)."""

    __tablename__ = "beat_runs"
    __table_args__ = (
        UniqueConstraint("job", "window_key", name="uq_beat_job_window"),
    )

    id = Column(Integer, primary_key=True, index=True)
    job = Column(String(50), nullable=False, index=True)  # rules_sweep | nightly | weekly
    window_key = Column(String(20), nullable=False)       # e.g. "2026-11-22" or "2026-W47"
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    ran_at = Column(String, server_default=func.now(), nullable=False)
    result = Column(JSON, nullable=True)                  # {"queued": 2, "skipped": 1, ...}

    def __repr__(self):
        return f"<BeatRun(job={self.job}, window={self.window_key}, ran_at={self.ran_at})>"
