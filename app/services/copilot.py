"""Copilot service — grounded context assembly, chat, and action proposals.

Every AI call executes as the logged-in user: context is filtered exactly like
the dashboard (user's assigned clients/projects), so RBAC and tenant isolation
are inherited, not rebuilt. Every entry carries a source tag so answers are
traceable to real records. Writes only ever happen via the proposal pattern:
draft → human confirm → execute.
"""
import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.ai_interaction import AiInteraction
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_task import UserTask

# Items sitting in a phase longer than this are "aging"
AGING_THRESHOLD_DAYS = 7

# Proposals expire after this many days pending
PROPOSAL_EXPIRY_DAYS = 7

# v1 operation vocabulary — each maps to an existing service call
PROPOSAL_OPS = ["advance_item", "assign_user", "create_risk_draft", "escalate_approval"]


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
    uid = user.id if user is not None else None

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
        proj_ids = _assigned_project_ids(db, user, tenant) if user is not None else []

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
        UserTask.assigned_to == uid if user is not None else None,
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


# ── Chat (grounded, read-only Q&A) ───────────────────────────────────────

CHAT_SYSTEM_PROMPT = (
    "You are the PMO Copilot — a project management assistant inside the PMO System. "
    "Answer only from the provided project data. Cite sources by record id "
    "(e.g. 'PMO-42' for a backlog item id=42, 'Approval #7' for an approval_request id=7). "
    "If the data doesn't contain the answer, say so plainly — never invent records. "
    "Be concise and operational: the user is a PM who needs to act."
)


def _call_llm(system_prompt: str, user_prompt: str, tenant_config: dict, max_tokens: int = 900) -> str:
    """Thin wrapper so tests can monkeypatch copilot_service._call_llm."""
    from app.services.ai import _call_llm as _ai_call
    return _ai_call(system_prompt, user_prompt, max_tokens=max_tokens, json_mode=True, tenant_config=tenant_config)


def copilot_chat(
    db: Session,
    user: User,
    tenant: Tenant,
    question: str,
    tenant_config: dict,
) -> dict:
    """Grounded Q&A over the user's data. Read-only: never writes records.

    Returns {answer, sources, interaction_id}.
    """
    from app.services.ai import _extract_json

    ctx = build_context(db, user, tenant)
    context_text = summarize_context(ctx)

    user_prompt = f"PROJECT DATA:\n{context_text}\n\nQUESTION: {question}"

    raw = _call_llm(CHAT_SYSTEM_PROMPT, user_prompt, tenant_config, max_tokens=900)
    parsed = _extract_json(raw) or {}
    answer = parsed.get("answer") or str(raw)
    sources = parsed.get("sources") or []

    interaction = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id,
        kind="query",
        question=question,
        answer=answer,
        sources=json.dumps(sources),
        status="pending",
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    return {"answer": answer, "sources": sources, "interaction_id": interaction.id}


# ── Action proposals (draft → human confirm → execute) ───────────────────

def copilot_propose(
    db: Session,
    user: User,
    tenant: Tenant,
    intent: str,
    operations: list[dict] | None = None,
    tenant_config: dict | None = None,
) -> dict:
    """Draft a write proposal from an intent. Executes nothing.

    If operations aren't given, the LLM compiles them from the intent using the
    v1 vocabulary. Operations are validated against PROPOSAL_OPS; anything else
    is rejected before drafting.
    """
    from app.services.ai import _extract_json

    if not operations:
        ctx = build_context(db, user, tenant)
        system = (
            "You compile PMO write operations. Reply ONLY with JSON: "
            '{"operations": [{"op": "advance_item"|"assign_user"|"create_risk_draft"|"escalate_approval", ...args}]}. '
            "Use only these four ops. Reference records by id from the data below. "
            "If the intent is out of scope, reply {\"operations\": []}."
        )
        raw = _call_llm(
            system,
            f"PROJECT DATA:\n{summarize_context(ctx)}\n\nINTENT: {intent}",
            tenant_config, max_tokens=700,
        )
        parsed = _extract_json(raw) or {}
        operations = parsed.get("operations") or []

    # Validate the vocabulary — unknown ops are dropped, never executed
    safe_ops = [op for op in operations if isinstance(op, dict) and op.get("op") in PROPOSAL_OPS]

    interaction = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id,
        kind="proposal",
        question=intent,
        proposal=json.dumps({"operations": safe_ops}),
        status="pending",
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    return {"proposal_id": interaction.id, "operations": safe_ops, "status": "pending"}


def get_proposal(db: Session, user: User, tenant: Tenant, proposal_id: int) -> AiInteraction | None:
    """Load a proposal owned by this user in this tenant; expire stale drafts."""
    row = db.query(AiInteraction).filter(
        AiInteraction.id == proposal_id,
        AiInteraction.tenant_id == tenant.id,
        AiInteraction.user_id == user.id,
        AiInteraction.kind == "proposal",
    ).first()
    if row and row.status == "pending" and _days_since(row.created_at) > PROPOSAL_EXPIRY_DAYS:
        row.status = "expired"
        db.commit()
    return row


def confirm_proposal(db: Session, user: User, tenant: Tenant, proposal_id: int) -> dict:
    """Execute a pending proposal AS the user, enforcing the user's authority.

    Every op re-checks the user's rights over the target record before writing.
    Returns {executed: [...], failed: [...]}.
    """
    row = get_proposal(db, user, tenant, proposal_id)
    if not row:
        return {"error": "Proposal not found", "status": 404}
    if row.status != "pending":
        return {"error": f"Proposal is {row.status}, only pending proposals can be confirmed", "status": 409}

    operations = json.loads(row.proposal or "{}").get("operations", [])
    executed, failed = [], []

    for op in operations:
        try:
            result = _execute_op(db, user, tenant, op)
            executed.append({"op": op, "result": result})
        except Exception as e:  # noqa: BLE001 — one failed op must not block the rest
            failed.append({"op": op, "error": str(e)[:200]})

    row.status = "approved"
    row.outcome = json.dumps({"executed": executed, "failed": failed})
    db.commit()

    return {"executed": executed, "failed": failed, "proposal_id": row.id}


def reject_proposal(db: Session, user: User, tenant: Tenant, proposal_id: int) -> dict:
    """Reject a pending proposal without executing anything."""
    row = get_proposal(db, user, tenant, proposal_id)
    if not row:
        return {"error": "Proposal not found", "status": 404}
    if row.status != "pending":
        return {"error": f"Proposal is {row.status}", "status": 409}
    row.status = "rejected"
    db.commit()
    return {"proposal_id": row.id, "status": "rejected"}


def _execute_op(db: Session, user: User, tenant: Tenant, op: dict) -> dict:
    """Execute one validated op with per-record permission checks.

    Authority ceiling: the proposal executes with the user's rights — an op the
    user couldn't do manually raises and lands in `failed`.
    """

    kind = op.get("op")

    if kind == "advance_item":
        item = db.query(BacklogItem).filter(
            BacklogItem.id == op.get("item_id"), BacklogItem.tenant_id == tenant.id,
        ).first()
        if not item:
            raise ValueError(f"Backlog item {op.get('item_id')} not found")
        project = db.query(Project).filter(Project.id == item.project_id).first()
        if not project or (project.project_manager_id != user.id and user.system_role != "super_admin"
                           and not _has_role_assignment(db, user.id, item.project_id)):
            raise PermissionError("You don't have rights over this project's items")
        target = op.get("target_phase") or item.current_phase
        old = item.current_phase
        item.current_phase = target
        db.add(ActivityLog(
            tenant_id=tenant.id, user_id=user.id, project_id=item.project_id,
            entity_type="backlog_item", entity_id=item.id, action="advanced",
            summary=f"{item.title} advanced {old} → {target} via Copilot proposal",
        ))
        db.commit()
        return {"item_id": item.id, "phase": target}

    if kind == "assign_user":
        item = db.query(BacklogItem).filter(
            BacklogItem.id == op.get("item_id"), BacklogItem.tenant_id == tenant.id,
        ).first()
        if not item:
            raise ValueError(f"Backlog item {op.get('item_id')} not found")
        project = db.query(Project).filter(Project.id == item.project_id).first()
        if not project or (project.project_manager_id != user.id and user.system_role != "super_admin"):
            raise PermissionError("Only the project manager can assign items")
        assignee = db.query(User).filter(User.id == op.get("assignee_id")).first()
        if not assignee:
            raise ValueError(f"User {op.get('assignee_id')} not found")
        item.assigned_to = assignee.id
        db.commit()
        return {"item_id": item.id, "assigned_to": assignee.id}

    if kind == "create_risk_draft":
        # v1: a risk DRAFT is an activity-log entry + note, not a Risk row (Risk model is P3)
        project_id = op.get("project_id")
        project = db.query(Project).filter(
            Project.id == project_id, Project.tenant_id == tenant.id,
        ).first() if project_id else None
        if not project:
            raise ValueError(f"Project {project_id} not found")
        db.add(ActivityLog(
            tenant_id=tenant.id, user_id=user.id, project_id=project.id,
            entity_type="risk_draft", entity_id=project.id, action="created",
            summary=f"Risk draft (Copilot): {op.get('description', '')[:200]}",
        ))
        db.commit()
        return {"project_id": project.id, "drafted": True}

    if kind == "escalate_approval":
        approval = db.query(ApprovalRequest).filter(
            ApprovalRequest.id == op.get("approval_id"), ApprovalRequest.tenant_id == tenant.id,
        ).first()
        if not approval:
            raise ValueError(f"Approval {op.get('approval_id')} not found")
        project = db.query(Project).filter(Project.id == approval.project_id).first()
        if not project or (project.project_manager_id != user.id and user.system_role != "super_admin"):
            raise PermissionError("Only the project manager can escalate this approval")
        note = op.get("note") or "Escalated via Copilot proposal"
        approval.description = f"{approval.description or ''}\n[ESCALATED] {note}".strip()
        db.commit()
        return {"approval_id": approval.id, "escalated": True}

    raise ValueError(f"Unknown op: {kind}")


def _has_role_assignment(db: Session, user_id: int, project_id: int) -> bool:
    from app.models.role_assignment import RoleAssignment
    return db.query(RoleAssignment).filter(
        RoleAssignment.user_id == user_id,
        RoleAssignment.project_id == project_id,
    ).first() is not None
