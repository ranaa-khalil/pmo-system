"""Time entries + timesheets API — manual hours log (Wrike parity, Q1).

GET    /api/projects/{id}/time-entries        list (?user_id=&from=&to=)
POST   /api/projects/{id}/time-entries        log hours (self, or PM for others)
DELETE /api/time-entries/{id}                 delete (own, or PM) — locked weeks reject
POST   /api/projects/{id}/timesheets/lock     lock a user's week (PM/tenant-admin/AM)
GET    /api/projects/{id}/time-summary        per-user totals vs budget
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import TenantMembership
from app.models.time_entry import TimeEntry, TimesheetLock
from app.models.user import User
from app.permissions import can_manage_project
from app.schemas.time_entry import (
    TimeEntryCreate,
    TimeEntryResponse,
    TimesheetLockRequest,
    TimeSummaryRow,
)

router = APIRouter(prefix="/api", tags=["time"])


def _week_start(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def _load_project(db: Session, project_id: int, user: User) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == user.id, TenantMembership.tenant_id == project.tenant_id,
    ).first()
    if not membership and user.system_role != "super_admin":
        raise HTTPException(403, "You don't have access to this project")
    return project


def _ensure_week_open(db: Session, project_id: int, user_id: int, entry_date: date) -> None:
    """The approval-locks-timesheet invariant: a locked week rejects writes."""
    ws = _week_start(entry_date)
    locked = db.query(TimesheetLock).filter(
        TimesheetLock.project_id == project_id,
        TimesheetLock.user_id == user_id,
        TimesheetLock.week_start == ws,
    ).first()
    if locked:
        raise HTTPException(409, f"Week starting {ws.isoformat()} is locked for this user")


@router.get("/projects/{project_id}/time-entries", response_model=list[TimeEntryResponse])
def list_entries(
    project_id: int,
    user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _load_project(db, project_id, current_user)
    query = db.query(TimeEntry).filter(TimeEntry.project_id == project_id)
    if user_id:
        query = query.filter(TimeEntry.user_id == user_id)
    if date_from:
        query = query.filter(TimeEntry.entry_date >= date_from)
    if date_to:
        query = query.filter(TimeEntry.entry_date <= date_to)
    return query.order_by(TimeEntry.entry_date.desc(), TimeEntry.id.desc()).all()


@router.post("/projects/{project_id}/time-entries", response_model=TimeEntryResponse, status_code=201)
def create_entry(
    project_id: int,
    req: TimeEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _load_project(db, project_id, current_user)
    target_user = req.user_id if req.user_id else current_user.id
    # Logging for someone else, or attaching to an item, needs manage rights
    if target_user != current_user.id and not can_manage_project(current_user, project, db):
        raise HTTPException(403, "You can only log your own hours")
    if req.item_id:
        item = db.query(BacklogItem).filter(
            BacklogItem.id == req.item_id, BacklogItem.project_id == project_id,
        ).first()
        if not item:
            raise HTTPException(404, "Item not found on this project")
    if req.hours <= 0 or req.hours > 24:
        raise HTTPException(422, "Hours must be between 0 and 24")
    _ensure_week_open(db, project_id, target_user, req.entry_date)
    entry = TimeEntry(
        tenant_id=project.tenant_id, project_id=project_id,
        item_id=req.item_id, user_id=target_user,
        entry_date=req.entry_date, hours=req.hours, note=req.note,
        created_by=current_user.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/time-entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    entry = db.query(TimeEntry).filter(TimeEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Entry not found")
    project = db.query(Project).filter(Project.id == entry.project_id).first()
    manager = project and can_manage_project(current_user, project, db)
    if entry.user_id != current_user.id and not manager:
        raise HTTPException(403, "You can only delete your own entries")
    _ensure_week_open(db, entry.project_id, entry.user_id, entry.entry_date)
    db.delete(entry)
    db.commit()


@router.post("/projects/{project_id}/timesheets/lock", status_code=201)
def lock_timesheet(
    project_id: int,
    req: TimesheetLockRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _load_project(db, project_id, current_user)
    if not can_manage_project(current_user, project, db):
        raise HTTPException(403, "You don't have permission to lock timesheets")
    ws = _week_start(req.week_start)
    existing = db.query(TimesheetLock).filter(
        TimesheetLock.project_id == project_id,
        TimesheetLock.user_id == req.user_id,
        TimesheetLock.week_start == ws,
    ).first()
    if existing:
        return {"id": existing.id, "user_id": req.user_id, "week_start": ws.isoformat(), "locked": True}
    lock = TimesheetLock(
        tenant_id=project.tenant_id, project_id=project_id,
        user_id=req.user_id, week_start=ws, locked_by=current_user.id,
    )
    db.add(lock)
    db.commit()
    db.refresh(lock)
    return {"id": lock.id, "user_id": req.user_id, "week_start": ws.isoformat(), "locked": True}


@router.delete("/projects/{project_id}/timesheets/lock", status_code=204)
def unlock_timesheet(
    project_id: int,
    user_id: int,
    week_start: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _load_project(db, project_id, current_user)
    if not can_manage_project(current_user, project, db):
        raise HTTPException(403, "You don't have permission to unlock timesheets")
    ws = _week_start(week_start)
    lock = db.query(TimesheetLock).filter(
        TimesheetLock.project_id == project_id,
        TimesheetLock.user_id == user_id,
        TimesheetLock.week_start == ws,
    ).first()
    if lock:
        db.delete(lock)
        db.commit()


@router.get("/projects/{project_id}/time-summary", response_model=list[TimeSummaryRow])
def time_summary(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _load_project(db, project_id, current_user)
    monday = _week_start(date.today())
    rows = (
        db.query(
            TimeEntry.user_id,
            User.name,
            sa_func.coalesce(sa_func.sum(TimeEntry.hours), 0).label("total"),
            sa_func.coalesce(sa_func.sum(case((TimeEntry.entry_date >= monday, TimeEntry.hours), else_=0)), 0).label("week"),
        )
        .outerjoin(User, User.id == TimeEntry.user_id)
        .filter(TimeEntry.project_id == project_id)
        .group_by(TimeEntry.user_id, User.name)
        .all()
    )
    return [
        TimeSummaryRow(user_id=r.user_id, name=r.name, total_hours=float(r.total), week_hours=float(r.week))
        for r in rows
    ]
