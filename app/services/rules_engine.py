"""Rules engine worker (P4.1) — evaluates enabled AutomationRule rows.

evaluate_rules(db, tenant) scans triggers against real data and executes
the action list (notify / create_task). Disabled rules never fire; actions
only use real records; fire bookkeeping (fire_count / last_fired_at) makes
repeated runs auditable.
"""
import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.approval import ApprovalRequest
from app.models.automation_rule import AutomationRule
from app.models.notification import Notification
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.user_task import UserTask

logger = logging.getLogger("app.rules_engine")


def _parse_created(value) -> datetime | None:
    """Tolerant parse of created_at (tz-aware or naive, ISO or space-separated)."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    s = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s.replace("+00:00", "")[:26] if ".%f" in fmt else s[:19] if "%H" in fmt else s[:10], fmt)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            continue
    return None


def _hours_since(value) -> float:
    dt = _parse_created(value)
    if not dt:
        return 0.0
    return (datetime.utcnow() - dt).total_seconds() / 3600.0


def _gate_owner(db: Session, approval: ApprovalRequest) -> User | None:
    """The pending step's approver, else the requester, else the tenant owner."""
    steps = sorted(approval.steps, key=lambda s: s.step_order) if getattr(approval, "steps", None) else []
    for step in steps:
        if (step.status or "Pending") == "Pending" and step.approver_id:
            approver = db.query(User).filter(User.id == step.approver_id).first()
            if approver:
                return approver
    if approval.requested_by:
        requester = db.query(User).filter(User.id == approval.requested_by).first()
        if requester:
            return requester
    membership = db.query(TenantMembership).filter(TenantMembership.tenant_id == approval.tenant_id, TenantMembership.role == "owner").first()
    return db.query(User).filter(User.id == membership.user_id).first() if membership else None


def _notify(db: Session, tenant: Tenant, user: User, title: str, body: str, project_id: int | None, link: str | None) -> None:
    db.add(Notification(
        tenant_id=tenant.id, user_id=user.id, type="automation",
        title=title[:255], body=body[:2000], link=link, project_id=project_id,
    ))


def _exec_notify(db: Session, tenant: Tenant, rule: AutomationRule, ctx: dict) -> int:
    """Notify the target role/user about the matched record."""
    target = ctx.get("user")
    if not target:
        return 0
    _notify(
        db, tenant, target,
        ctx["title"], ctx["body"], ctx.get("project_id"), ctx.get("link"),
    )
    return 1


def _exec_create_task(db: Session, tenant: Tenant, rule: AutomationRule, ctx: dict) -> int:
    """Create an escalation task assigned to the matched record's owner."""
    target = ctx.get("user")
    if not target:
        return 0
    prefix = ""
    for action in rule.actions or []:
        if action.get("type") == "create_task":
            prefix = action.get("title_prefix", "")
    title = f"{prefix}{ctx['title']}"
    exists = (
        db.query(UserTask)
        .filter(UserTask.tenant_id == tenant.id, UserTask.title == title, UserTask.status != "Completed")
        .first()
    )
    if exists:
        return 0  # idempotent: never duplicate an escalation task
    db.add(UserTask(
        tenant_id=tenant.id, title=title[:500],
        description=ctx["body"][:2000], assigned_to=target.id,
        project_id=ctx.get("project_id"), priority="High", status="Pending",
    ))
    return 1


_EXECUTORS = {"notify": _exec_notify, "create_task": _exec_create_task}


def _match_approval_aging(db: Session, tenant: Tenant, rule: AutomationRule) -> list[dict]:
    """Pending approvals older than conditions.hours_in_gate."""
    hours = float((rule.conditions or {}).get("hours_in_gate", 48))
    approvals = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.tenant_id == tenant.id, ApprovalRequest.status == "Pending")
        .all()
    )
    ctxs = []
    for a in approvals:
        age = _hours_since(a.created_at)
        if age >= hours:
            owner = _gate_owner(db, a)
            if not owner:
                continue
            ctxs.append({
                "user": owner, "project_id": a.project_id,
                "title": a.title, "link": f"#/approvals/{a.id}",
                "body": f"This gate has been pending for {int(age)}h (threshold {int(hours)}h). Rule: {rule.name}.",
            })
    return ctxs


def _match_task_overdue(db: Session, tenant: Tenant, rule: AutomationRule) -> list[dict]:
    """User tasks past their due date by conditions.days_overdue."""
    days = int((rule.conditions or {}).get("days_overdue", 1))
    tasks = (
        db.query(UserTask)
        .filter(UserTask.tenant_id == tenant.id, UserTask.status != "Completed", UserTask.due_date.isnot(None))
        .all()
    )
    today = date.today()
    ctxs = []
    for t in tasks:
        overdue_days = (today - t.due_date).days
        if overdue_days >= days:
            assignee = db.query(User).filter(User.id == t.assigned_to).first()
            if not assignee:
                continue
            ctxs.append({
                "user": assignee, "project_id": t.project_id,
                "title": t.title, "link": None,
                "body": f"Task overdue by {overdue_days} day(s). Rule: {rule.name}.",
            })
    return ctxs


def _match_item_sent_back(db: Session, tenant: Tenant, rule: AutomationRule) -> list[dict]:
    """Backlog items sent back within the last conditions.within_hours."""
    within = float((rule.conditions or {}).get("within_hours", 24))
    logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.tenant_id == tenant.id,
            ActivityLog.entity_type == "backlog_item",
            ActivityLog.action.in_(["sent_back", "updated"]),
            ActivityLog.summary.like("%sent back%"),
        )
        .all()
    )
    ctxs = []
    for log in logs:
        age = _hours_since(log.created_at)
        if age <= within and log.user_id:
            actor = db.query(User).filter(User.id == log.user_id).first()
            if not actor:
                continue
            ctxs.append({
                "user": actor, "project_id": log.project_id,
                "title": log.summary[:255], "link": None,
                "body": f"Item sent back {int(age)}h ago. Rule: {rule.name}.",
            })
    return ctxs


_MATCHERS = {
    "approval_aging": _match_approval_aging,
    "task_overdue": _match_task_overdue,
    "item_sent_back": _match_item_sent_back,
}


def evaluate_rules(db: Session, tenant: Tenant) -> dict:
    """Evaluate every enabled rule for the tenant; execute matched actions.

    Returns {"evaluated": N, "fired": M, "details": [...]} — counts only;
    the notification/task rows are the audit trail.
    """
    rules = (
        db.query(AutomationRule)
        .filter(AutomationRule.tenant_id == tenant.id, AutomationRule.enabled.is_(True))
        .all()
    )
    fired = 0
    details = []
    now_iso = datetime.utcnow().isoformat()
    for rule in rules:
        matcher = _MATCHERS.get(rule.trigger)
        if not matcher:
            continue
        ctxs = matcher(db, tenant, rule)
        for ctx in ctxs:
            rule_fired = False
            for action in rule.actions or []:
                executor = _EXECUTORS.get(action.get("type"))
                if executor and executor(db, tenant, rule, ctx):
                    rule_fired = True
            if rule_fired:
                fired += 1
                details.append({"rule": rule.name, "record": ctx["title"]})
        if ctxs:
            rule.fire_count = (rule.fire_count or 0) + len(ctxs)
            rule.last_fired_at = now_iso
    db.commit()
    return {"evaluated": len(rules), "fired": fired, "details": details}
