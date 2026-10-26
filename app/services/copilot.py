"""Copilot service — grounded context assembly, chat, and action proposals.

Every AI call executes as the logged-in user: context is filtered exactly like
the dashboard (user's assigned clients/projects), so RBAC and tenant isolation
are inherited, not rebuilt. Every entry carries a source tag so answers are
traceable to real records.
"""
import json
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_task import UserTask

# Items sitting in a phase longer than this are "aging"
AGING_THRESHOLD_DAYS = 7


def _assigned_project_ids(db: Session, user: User, tenant: Tenant) -> list[int]:
    """Projects where the user is PM or holds a RACI role assignment —
    same filtering as app/routers/dashboard.py."""
    from app.models.role_assignment import RoleAssignment

    tid = tenant.id
    ids: set[int] = set()
    for (pid,) in db.query(Project.id).filter(
        Project.tenant_id == tid, Project.project_manager_id == user.id,
    ).all():
        ids.add(pid)
    for (pid,) in db.query(RoleAssignment.project_id).filter(
        RoleAssignment.user_id == user.id,
    ).all():
        p = db.query(Project).filter(Project.id == pid, Project.tenant_id == tid).first()
        if p:
            ids.add(pid)
    return sorted(ids)


def build_context(
    db: Session,
    user: User,
    tenant: Tenant,
    project_id: int | None = None,
) -> dict:
    """Assemble the grounded system state the copilot can see.

    Returns a dict of lists; every entry has entity_type/entity_id/title so the
    UI can render source chips and the LLM can cite record ids.
    """
    tid = tenant.id
    uid = user.id

    if project_id is not None:
        project = db.query(Project).filter(
            Project.id == project_id, Project.tenant_id == tid,
        ).first()
        if not project:
            return {
                "projects": [], "pending_approvals": [], "aging_items": [],
                "overdue_tasks": [], "at_risk_releases": [], "epic_tree": {},
            }
        proj_ids = [project.id]
    else:
        proj_ids = _assigned_project_ids(db, user, tenant)

    if not proj_ids:
        return {
            "projects": [], "pending_approvals": [], "aging_items": [],
            "overdue_tasks": [], "at_risk_releases": [], "epic_tree": {},
        }

    projects = db.query(Project).filter(
        Project.tenant_id == tid, Project.id.in_(proj_ids),
    ).order_by(Project.id).all()

    # ── Pending approvals in the user's projects ─────────────────────────
    approvals = db.query(ApprovalRequest).filter(
        ApprovalRequest.status == "Pending",
        ApprovalRequest.project_id.in_(proj_ids),
    ).order_by(ApprovalRequest.id.desc()).all()

    pending_approvals = []
    for a in approvals:
        step = db.query(ApprovalStep).filter(
            ApprovalStep.request_id == a.id,
            ApprovalStep.status == "Pending",
        ).order_by(ApprovalStep.step_order).first()
        pending_approvals.append({
            "entity_type": "approval_request", "entity_id": a.id,
            "title": a.title, "project_id": a.project_id,
            "request_type": a.request_type, "target_phase": a.target_phase,
            "awaiting_role": step.role_name if step else None,
        })

    # ── Aging items: last movement per item from the activity log ────────
    aging_items = []
    items = db.query(BacklogItem).filter(
        BacklogItem.project_id.in_(proj_ids),
        BacklogItem.status.in_(["In Progress", "Blocked", "Draft"]),
    ).all()
    last_movement = {}
    for (entity_id, latest) in db.query(
        ActivityLog.entity_id, ActivityLog.created_at,
    ).filter(
        ActivityLog.entity_type == "backlog_item",
        ActivityLog.action.in_(["advanced", "updated", "assigned"]),
    ).order_by(ActivityLog.created_at.desc()).all():
        if entity_id not in last_movement:
            last_movement[entity_id] = latest

    for item in items:
        last = last_movement.get(item.id) or item.created_at
        days = _days_since(last)
        if days >= AGING_THRESHOLD_DAYS:
            aging_items.append({
                "entity_type": "backlog_item", "entity_id": item.id,
                "title": item.title, "project_id": item.project_id,
                "phase": item.current_phase, "status": item.status,
                "epic": item.epic, "days_in_phase": days,
            })
    aging_items.sort(key=lambda e: -e["days_in_phase"])

    # ── Overdue tasks assigned to this user ──────────────────────────────
    today = date.today()
    tasks = db.query(UserTask).filter(
        UserTask.assigned_to == uid,
        UserTask.status == "Pending",
        UserTask.project_id.in_(proj_ids),
    ).all()
    overdue_tasks = []
    for t in tasks:
        if t.due_date:
            try:
                due = t.due_date if isinstance(t.due_date, date) else date.fromisoformat(str(t.due_date))
            except ValueError:
                continue
            if due < today:
                overdue_tasks.append({
                    "entity_type": "user_task", "entity_id": t.id,
                    "title": t.title, "project_id": t.project_id,
                    "due_date": str(t.due_date), "days_overdue": (today - due).days,
                })
    overdue_tasks.sort(key=lambda e: -e["days_overdue"])

    # ── At-risk releases: pending approval or past target date ───────────
    at_risk_releases = []
    releases = db.query(Release).filter(
        Release.tenant_id == tid, Release.project_id.in_(proj_ids),
        Release.status.in_(["Planning", "In Progress", "Testing", "UAT"]),
    ).all()
    for rel in releases:
        reasons = []
        if rel.target_date:
            try:
                target = rel.target_date if isinstance(rel.target_date, date) else date.fromisoformat(str(rel.target_date))
                if target < today:
                    reasons.append(f"target date {rel.target_date} passed")
            except ValueError:
                pass
        if any(a["project_id"] == rel.project_id for a in pending_approvals):
            reasons.append("has a pending gate approval")
        if reasons:
            at_risk_releases.append({
                "entity_type": "release", "entity_id": rel.id,
                "title": f"{rel.version} {rel.name}".strip(),
                "project_id": rel.project_id, "status": rel.status,
                "reasons": reasons,
            })

    epic_tree = _epic_tree(db, proj_ids)

    return {
        "projects": [
            {"entity_type": "project", "entity_id": p.id, "title": p.name,
             "status": p.status} for p in projects
        ],
        "pending_approvals": pending_approvals,
        "aging_items": aging_items,
        "overdue_tasks": overdue_tasks,
        "at_risk_releases": at_risk_releases,
        "epic_tree": epic_tree,
    }


def _epic_tree(db: Session, proj_ids: list[int]) -> dict:
    """Epic → features map for intake verdicts and backlog questions."""
    items = db.query(BacklogItem).filter(
        BacklogItem.project_id.in_(proj_ids),
    ).order_by(BacklogItem.id).all()
    tree: dict[str, dict] = {}
    for item in items:
        epic = item.epic or "Ungrouped"
        node = tree.setdefault(epic, {"entity_type": "epic", "title": epic, "features": []})
        node["features"].append({
            "entity_type": "backlog_item", "entity_id": item.id,
            "title": item.title, "phase": item.current_phase,
            "status": item.status, "item_type": item.item_type,
        })
    return tree


def _days_since(value) -> int:
    """Days since a datetime/string timestamp; 0 when unparseable."""
    if value is None:
        return 0
    if isinstance(value, datetime):
        return (datetime.utcnow() - value).days
    if isinstance(value, date):
        return (date.today() - value).days
    s = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(s[:26] if ".%f" in fmt else s[:19] if "%H" in fmt else s[:10], fmt)
            return (datetime.utcnow() - parsed).days if "%H" in fmt else (date.today() - parsed.date()).days
        except ValueError:
            continue
    return 0


def summarize_context(ctx: dict, max_items: int = 40) -> str:
    """Compact text rendering of the context for the LLM prompt."""
    lines: list[str] = []
    if ctx["projects"]:
        lines.append("PROJECTS: " + "; ".join(f"{p['title']} (id={p['entity_id']}, {p['status']})" for p in ctx["projects"]))
    if ctx["pending_approvals"]:
        rows = [f"- {a['title']} (id={a['entity_id']}, awaiting {a.get('awaiting_role') or 'next role'})" for a in ctx["pending_approvals"][:max_items]]
        lines.append("PENDING GATE APPROVALS:\n" + "\n".join(rows))
    if ctx["overdue_tasks"]:
        rows = [f"- {t['title']} (id={t['entity_id']}, {t['days_overdue']} days overdue)" for t in ctx["overdue_tasks"][:max_items]]
        lines.append("YOUR OVERDUE TASKS:\n" + "\n".join(rows))
    if ctx["aging_items"]:
        rows = [f"- {i['title']} (id={i['entity_id']}) — {i['phase']} for {i['days_in_phase']} days" for i in ctx["aging_items"][:max_items]]
        lines.append("ITEMS AGING IN PHASE:\n" + "\n".join(rows))
    if ctx["at_risk_releases"]:
        rows = [f"- {r['title']} (id={r['entity_id']}): {'; '.join(r['reasons'])}" for r in ctx["at_risk_releases"][:max_items]]
        lines.append("AT-RISK RELEASES:\n" + "\n".join(rows))
    return "\n\n".join(lines) if lines else "No signal data found for your assignments."
