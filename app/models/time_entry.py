"""TimeEntry + TimesheetLock models — manual hours log (Wrike parity, Q1).

No timers: users log hours per project/item/day with a note. A PM can lock a
user's weekly timesheet — once locked, entries in that week are frozen
(the approval-locks-timesheet invariant).
"""
from sqlalchemy import Column, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("backlog_items.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    entry_date = Column(Date, nullable=False)
    hours = Column(Numeric(5, 2), nullable=False)
    note = Column(Text, nullable=True)

    created_at = Column(String, server_default=func.now(), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    def __repr__(self):
        return f"<TimeEntry(id={self.id}, project={self.project_id}, user={self.user_id}, hours={self.hours})>"


class TimesheetLock(Base):
    __tablename__ = "timesheet_locks"
    __table_args__ = (UniqueConstraint("project_id", "user_id", "week_start", name="uq_timesheet_lock"),)

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    week_start = Column(Date, nullable=False)  # Monday of the locked week
    locked_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)
