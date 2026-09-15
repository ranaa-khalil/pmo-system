"""Notifications router — in-app notifications + activity log + data export."""
import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.activity_log import ActivityLog
from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
from app.models.notification import Notification
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user import User as UserModel
from app.models.user_task import UserTask
from app.services.notifications import ensure_preferences
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["notifications"])


def _get_user_from_token(token: str, db: Session) -> User:
    """Parse a JWT token and return the user (for query-param auth on exports)."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(401, "Invalid token")
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(401, "User not found")
    return user


def _resolve_tenant_id(user: User, db: Session) -> int:
    """Resolve the user's active tenant ID for token-based endpoints."""
    if user.active_tenant_id:
        return user.active_tenant_id
    from app.models.tenant import TenantMembership
    membership = db.query(TenantMembership).filter(TenantMembership.user_id == user.id).first()
    if membership:
        user.active_tenant_id = membership.tenant_id
        db.commit()
        return membership.tenant_id
    raise HTTPException(403, "User is not a member of any tenant.")


# ==================== NOTIFICATIONS ====================

@router.get("/notifications")
def get_notifications(
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get current user's notifications."""
    tid = current_tenant.id
    q = db.query(Notification).filter(Notification.user_id == current_user.id, Notification.tenant_id == tid)
    if unread_only:
        q = q.filter(Notification.read == False)
    notifs = q.order_by(Notification.created_at.desc()).limit(limit).all()
    unread_count = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.read == False,
        Notification.tenant_id == tid,
    ).count()
    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "read": n.read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "project_id": n.project_id,
            }
            for n in notifs
        ],
        "unread_count": unread_count,
    }


@router.put("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Mark a single notification as read."""
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
        Notification.tenant_id == current_tenant.id,
    ).first()
    if not notif:
        raise HTTPException(404, "Notification not found")
    notif.read = True
    db.commit()
    return {"ok": True}


@router.put("/notifications/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Mark all notifications as read."""
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.read == False,
        Notification.tenant_id == current_tenant.id,
    ).update({"read": True})
    db.commit()
    return {"ok": True}


@router.delete("/notifications/{notification_id}")
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete a notification."""
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
        Notification.tenant_id == current_tenant.id,
    ).first()
    if not notif:
        raise HTTPException(404, "Notification not found")
    db.delete(notif)
    db.commit()
    return {"ok": True}


# ==================== NOTIFICATION PREFERENCES ====================

@router.get("/notifications/preferences")
def get_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get current user's notification preferences."""
    pref = ensure_preferences(db, current_user.id)
    return {
        "email_enabled": pref.email_enabled,
        "in_app_enabled": pref.in_app_enabled,
        "approval_requests": pref.approval_requests,
        "task_reminders": pref.task_reminders,
        "release_updates": pref.release_updates,
        "daily_digest": pref.daily_digest,
        "digest_time": pref.digest_time,
    }


@router.put("/notifications/preferences")
def update_preferences(
    prefs: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Update current user's notification preferences."""
    pref = ensure_preferences(db, current_user.id)
    for field in ["email_enabled", "in_app_enabled", "approval_requests",
                  "task_reminders", "release_updates", "daily_digest"]:
        if field in prefs:
            setattr(pref, field, bool(prefs[field]))
    if "digest_time" in prefs:
        pref.digest_time = prefs["digest_time"]
    db.commit()
    return {"ok": True}


# ==================== ACTIVITY LOG ====================

@router.get("/activity")
def get_activity(
    project_id: int = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get activity log entries (global or per-project)."""
    q = db.query(ActivityLog).filter(ActivityLog.tenant_id == current_tenant.id)
    if project_id:
        q = q.filter(ActivityLog.project_id == project_id)
    entries = q.order_by(ActivityLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "user_id": e.user_id,
            "user_name": e.user_name,
            "project_id": e.project_id,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "action": e.action,
            "summary": e.summary,
            "changes": json.loads(e.changes) if e.changes else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


# ==================== DATA EXPORT ====================

@router.get("/export/backlog/{project_id}")
def export_backlog(
    project_id: int,
    token: str = None,
    db: Session = Depends(get_db),
):
    """Export project backlog to CSV."""
    if not token:
        raise HTTPException(401, "Token required")
    current_user = _get_user_from_token(token, db)
    tid = _resolve_tenant_id(current_user, db)
    items = db.query(BacklogItem).filter(BacklogItem.project_id == project_id, BacklogItem.tenant_id == tid).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Title", "Type", "Phase", "Priority", "Story Points",
                     "Primary Actor", "Epic", "Target Release", "Created At"])

    for item in items:
        writer.writerow([
            item.id, item.title, item.item_type or "", item.current_phase, item.priority,
            item.story_points or "", item.primary_actor or "",
            item.epic or "", item.target_release or "",
            str(item.created_at) if item.created_at else "",
        ])

    output.seek(0)
    project = db.query(Project).filter(Project.id == project_id, Project.tenant_id == tid).first()
    filename = f"backlog_{project.name.replace(' ', '_').lower()}.csv" if project else "backlog.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/tasks")
def export_tasks(
    token: str = None,
    db: Session = Depends(get_db),
):
    """Export current user's tasks to CSV."""
    if not token:
        raise HTTPException(401, "Token required")
    current_user = _get_user_from_token(token, db)
    tid = _resolve_tenant_id(current_user, db)
    tasks = db.query(UserTask).filter(UserTask.assigned_to == current_user.id, UserTask.tenant_id == tid).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Title", "Description", "Status", "Priority",
                     "Due Date", "Project ID", "Milestone ID", "Reminder Days",
                     "Created At"])

    for t in tasks:
        writer.writerow([
            t.id, t.title, t.description or "", t.status, t.priority,
            str(t.due_date) if t.due_date else "",
            t.project_id or "", t.milestone_id or "",
            t.reminder_days, str(t.created_at) if t.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=my_tasks.csv"}
    )


@router.get("/export/kpis/{project_id}")
def export_kpis(
    project_id: int,
    token: str = None,
    db: Session = Depends(get_db),
):
    """Export project KPIs to CSV."""
    if not token:
        raise HTTPException(401, "Token required")
    current_user = _get_user_from_token(token, db)
    tid = _resolve_tenant_id(current_user, db)
    kpis = db.query(KPI).filter(KPI.project_id == project_id, KPI.tenant_id == tid).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Category", "Target", "Current",
                     "Unit", "Progress %"])

    for k in kpis:
        try:
            target = float(k.target_value) if k.target_value else 0
            current = float(k.current_value) if k.current_value else 0
        except (ValueError, TypeError):
            target, current = 0, 0
        pct = int((current / target * 100) if target else 0)
        writer.writerow([
            k.id, k.name, k.category or "", target, current,
            k.unit or "", pct,
        ])

    output.seek(0)
    project = db.query(Project).filter(Project.id == project_id, Project.tenant_id == tid).first()
    filename = f"kpis_{project.name.replace(' ', '_').lower()}.csv" if project else "kpis.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ==================== PROJECT HEALTH ====================

@router.get("/projects/{project_id}/health")
def get_project_health(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get composite project health score and breakdown."""
    tid = current_tenant.id
    from app.models.approval import ApprovalRequest
    from app.models.release import Release, ReleaseItem

    # Phase distribution
    items = db.query(BacklogItem).filter(BacklogItem.project_id == project_id, BacklogItem.tenant_id == tid).all()
    phase_dist = {}
    for item in items:
        phase_dist[item.current_phase] = phase_dist.get(item.current_phase, 0) + 1

    total_items = len(items)
    completed_items = sum(1 for i in items if i.current_phase == "Ready for UAT" or i.target_release)

    # Active releases
    releases = db.query(Release).filter(Release.project_id == project_id, Release.tenant_id == tid).all()
    active_releases = [r for r in releases if r.status not in ("Post-Release",)]
    releases_with_items = []
    for r in active_releases:
        release_items = db.query(ReleaseItem).filter(ReleaseItem.release_id == r.id, ReleaseItem.tenant_id == tid).all()
        releases_with_items.append({
            "id": r.id,
            "version": r.version,
            "name": r.name,
            "status": r.status,
            "item_count": len(release_items),
            "progress": min(100, len(release_items) * 20),
        })

    # Pending approvals
    pending_approvals = db.query(ApprovalRequest).filter(
        ApprovalRequest.project_id == project_id,
        ApprovalRequest.status == "Pending",
        ApprovalRequest.tenant_id == tid,
    ).count()

    # Overdue tasks
    from datetime import date as _date
    today = _date.today()
    overdue_tasks = db.query(UserTask).filter(
        UserTask.project_id == project_id,
        UserTask.status != "Completed",
        UserTask.due_date < today,
        UserTask.tenant_id == tid,
    ).count()

    # KPIs below target
    kpis = db.query(KPI).filter(KPI.project_id == project_id, KPI.tenant_id == tid).all()
    kpis_below = 0
    kpi_progress = []
    for k in kpis:
        try:
            target = float(k.target_value) if k.target_value else 0
            current = float(k.current_value) if k.current_value else 0
        except (ValueError, TypeError):
            target, current = 0, 0
        if target and current < target:
            kpis_below += 1
        pct = int((current / target * 100) if target else 0)
        kpi_progress.append({
            "id": k.id, "name": k.name, "current": current,
            "target": target, "unit": k.unit, "progress": min(100, pct),
        })

    # Composite health score (0-100)
    schedule_score = min(100, (completed_items / total_items * 100) if total_items else 100)
    approval_score = max(0, 100 - pending_approvals * 15)
    task_score = max(0, 100 - overdue_tasks * 20)
    kpi_score = (len(kpis) - kpis_below) / len(kpis) * 100 if kpis else 100
    health_score = int((schedule_score + approval_score + task_score + kpi_score) / 4)

    # Determine status
    if health_score >= 80:
        status = "Healthy"
        status_color = "emerald"
    elif health_score >= 60:
        status = "At Risk"
        status_color = "amber"
    elif health_score >= 40:
        status = "Warning"
        status_color = "orange"
    else:
        status = "Critical"
        status_color = "rose"

    return {
        "health_score": health_score,
        "status": status,
        "status_color": status_color,
        "schedule_score": int(schedule_score),
        "approval_score": int(approval_score),
        "task_score": int(task_score),
        "kpi_score": int(kpi_score),
        "total_items": total_items,
        "completed_items": completed_items,
        "phase_distribution": phase_dist,
        "active_releases": releases_with_items,
        "pending_approvals": pending_approvals,
        "overdue_tasks": overdue_tasks,
        "kpis_below_target": kpis_below,
        "kpi_progress": kpi_progress,
    }
