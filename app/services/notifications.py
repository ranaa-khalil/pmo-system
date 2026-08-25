"""Notification service — creates notifications and sends emails.

Used by routers (approvals, releases, backlog, user_tasks) to notify users
of important events without coupling them to notification implementation details.
"""
import json
from datetime import datetime, date
from sqlalchemy.orm import Session
from app.models.notification import Notification, NotificationPreference
from app.models.activity_log import ActivityLog
from app.models.user import User


def create_notification(
    db: Session,
    user_id: int,
    type: str,
    title: str,
    body: str = None,
    link: str = None,
    project_id: int = None,
):
    """Create an in-app notification for a user (respects their preferences)."""
    pref = db.query(NotificationPreference).filter(
        NotificationPreference.user_id == user_id
    ).first()

    # Check if user wants this type of notification
    if pref:
        if not pref.in_app_enabled:
            return None
        type_map = {
            "approval_request": pref.approval_requests,
            "approval_approved": pref.approval_requests,
            "approval_rejected": pref.approval_requests,
            "task_due": pref.task_reminders,
            "task_overdue": pref.task_reminders,
            "release_advanced": pref.release_updates,
            "item_sent_back": pref.release_updates,
            "phase_changed": pref.release_updates,
        }
        if not type_map.get(type, True):
            return None

    notif = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        link=link,
        project_id=project_id,
    )
    db.add(notif)
    db.flush()  # get ID without full commit
    return notif


def log_activity(
    db: Session,
    user_id: int,
    user_name: str,
    project_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    summary: str,
    changes: dict = None,
):
    """Create an immutable activity log entry."""
    entry = ActivityLog(
        user_id=user_id,
        user_name=user_name,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        summary=summary,
        changes=json.dumps(changes) if changes else None,
    )
    db.add(entry)
    db.flush()
    return entry


def notify_approval_created(db: Session, approval_id: int, step_role: str,
                            assignee_id: int, project_id: int, release_name: str):
    """Notify the gate-keeper that an approval request was created for them."""
    create_notification(
        db, assignee_id, "approval_request",
        f"Approval needed: {step_role} gate",
        f"Release '{release_name}' is awaiting your sign-off as {step_role}.",
        link=f"/projects/{project_id}/approvals",
        project_id=project_id,
    )


def notify_approval_result(db: Session, approved: bool, approver_name: str,
                           release_name: str, gate_role: str, pm_id: int,
                           project_id: int):
    """Notify the PM that an approval was approved or rejected."""
    type_ = "approval_approved" if approved else "approval_rejected"
    status = "approved" if approved else "rejected"
    create_notification(
        db, pm_id, type_,
        f"Gate {status}: {gate_role}",
        f"{approver_name} {status} the {gate_role} gate for release '{release_name}'.",
        link=f"/projects/{project_id}/releases",
        project_id=project_id,
    )


def notify_task_due_soon(db: Session, task_title: str, due_date: date,
                         user_id: int):
    """Notify a user that a task is due soon."""
    create_notification(
        db, user_id, "task_due",
        f"Task due soon: {task_title}",
        f"Due on {due_date.strftime('%b %d')}.",
        link="/tasks",
    )


def notify_task_overdue(db: Session, task_title: str, due_date: date,
                        user_id: int):
    """Notify a user that a task is overdue."""
    create_notification(
        db, user_id, "task_overdue",
        f"⚠ Task overdue: {task_title}",
        f"Was due on {due_date.strftime('%b %d')}.",
        link="/tasks",
    )


def notify_release_advanced(db: Session, release_name: str, new_phase: str,
                            stakeholders: list, project_id: int):
    """Notify all project stakeholders that a release advanced to a new phase."""
    for s in stakeholders:
        if s.user_id:
            create_notification(
                db, s.user_id, "release_advanced",
                f"Release advanced: {release_name}",
                f"'{release_name}' moved to {new_phase} phase.",
                link=f"/projects/{project_id}/releases",
                project_id=project_id,
            )


def notify_item_sent_back(db: Session, item_title: str, developer_id: int,
                          project_id: int):
    """Notify the developer that their item was sent back from Testing."""
    if developer_id:
        create_notification(
            db, developer_id, "item_sent_back",
            f"Item sent back: {item_title}",
            f"'{item_title}' was sent back from Testing to Development.",
            link=f"/projects/{project_id}/backlog",
            project_id=project_id,
        )


def ensure_preferences(db: Session, user_id: int):
    """Create default notification preferences for a user if they don't have any."""
    existing = db.query(NotificationPreference).filter(
        NotificationPreference.user_id == user_id
    ).first()
    if not existing:
        pref = NotificationPreference(user_id=user_id)
        db.add(pref)
        db.flush()
        return pref
    return existing
