"""Officer beat services — the day report and the RAID escalation template.

R1 of the rebuild: the officer runtime makes "humans tell, decide, read" real.
- publish_day_reports: the officer's day report published to Today — one in-app
  notification per member with pending work ("what needs you"), deduped per
  user per day.
- ensure_rule_templates: seeds the RAID escalation rule template
  (Blocked > N days → escalation task, amber-confirm) once per tenant.
  Rules are NEVER auto-enabled (P4.1) — a human flips enabled=True.
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.approval import ApprovalRequest
from app.models.automation_rule import AutomationRule
from app.models.notification import Notification
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.user_task import UserTask
from app.services.notifications import create_notification
from app.services.rules_engine import _gate_owner, _parse_created

logger = logging.getLogger("app.officer")

# The RAID escalation rule template (decision-7, 🐙): a backlog item that sat
# Blocked > N days raises an escalation follow-up — amber-confirm, never auto-
# executed. Seeded DISABLED; the human enables it.
ESCALATION_TEMPLATE = {
    "name": "Blocked escalation",
    "description": "A backlog item Blocked for more than N days raises an "
                   "escalation task for its owner (decision-7). Seeded by the "
                   "officer beat; enable it to turn on.",
    "trigger": "item_blocked",
    "conditions": {"days_blocked": 3},
    "actions": [
        {"type": "notify", "role": "assignee"},
        {"type": "create_task", "title_prefix": "Escalate: "},
    ],
    "source": "template",
    "enabled": False,
}


def ensure_rule_templates(db: Session, tenant: Tenant) -> dict:
    """Seed the escalation rule template once per tenant (idempotent)."""
    exists = (
        db.query(AutomationRule)
        .filter(
            AutomationRule.tenant_id == tenant.id,
            AutomationRule.trigger == ESCALATION_TEMPLATE["trigger"],
            AutomationRule.source == "template",
        )
        .first()
    )
    if exists:
        return {"seeded": 0}
    db.add(AutomationRule(tenant_id=tenant.id, **ESCALATION_TEMPLATE))
    db.commit()
    logger.info("Seeded escalation rule template for tenant %s", tenant.id)
    return {"seeded": 1}


def _pending_approval_counts(db: Session, tenant: Tenant) -> dict[int, int]:
    """Approvals waiting per gate owner across the tenant's projects."""
    pending = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.tenant_id == tenant.id)
        .filter(ApprovalRequest.status == "Pending")
        .all()
    )
    counts: dict[int, int] = {}
    for approval in pending:
        owner = _gate_owner(db, approval)
        if owner:
            counts[owner.id] = counts.get(owner.id, 0) + 1
    return counts


def _overdue_task_counts(db: Session, tenant: Tenant) -> dict[int, int]:
    """Overdue tasks per assignee across the tenant."""
    today = datetime.utcnow().date()
    tasks = (
        db.query(UserTask)
        .filter(UserTask.tenant_id == tenant.id)
        .filter(UserTask.status != "Completed")
        .all()
    )
    counts: dict[int, int] = {}
    for task in tasks:
        due = _parse_created(task.due_date) if getattr(task, "due_date", None) else None
        if due and due.date() < today and task.assigned_to:
            counts[task.assigned_to] = counts.get(task.assigned_to, 0) + 1
    return counts


def publish_day_reports(db: Session, tenant: Tenant) -> dict:
    """The officer's day report, published to Today: one in-app notification
    per member with pending work. Deduped per user per day."""
    approvals = _pending_approval_counts(db, tenant)
    overdue = _overdue_task_counts(db, tenant)

    memberships = (
        db.query(TenantMembership)
        .filter(TenantMembership.tenant_id == tenant.id)
        .all()
    )
    published, skipped = 0, 0
    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    for m in memberships:
        user = db.query(User).filter(User.id == m.user_id).first()
        if not user:
            continue
        n_approvals = approvals.get(user.id, 0)
        n_overdue = overdue.get(user.id, 0)
        if n_approvals == 0 and n_overdue == 0:
            skipped += 1
            continue
        # Dedupe: one day report per user per day
        already = (
            db.query(Notification)
            .filter(
                Notification.user_id == user.id,
                Notification.type == "day_report",
                Notification.created_at >= today_iso,
            )
            .first()
        )
        if already:
            skipped += 1
            continue
        parts = []
        if n_approvals:
            parts.append(f"{n_approvals} approval{'s' if n_approvals != 1 else ''} need{'s' if n_approvals == 1 else ''} your decision")
        if n_overdue:
            parts.append(f"{n_overdue} overdue task{'s' if n_overdue != 1 else ''}")
        create_notification(
            db, user.id, "day_report",
            title="Your day",
            body=" · ".join(parts) + ".",
            link="/today",
            project_id=None,
        )
        published += 1
    db.commit()
    return {"kind": "day_reports", "published": published, "skipped": skipped}
