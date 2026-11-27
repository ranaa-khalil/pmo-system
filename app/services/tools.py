"""Read-only tool registry — the copilot's bounded Ask escalation (phase 3).

When the grounding bundles can't answer (broad, multi-hop questions like
"which project has the most overdue items and who owns them?"), the reasoned
writer may escalate to a BOUNDED loop over this registry: max
TOOL_LOOP_MAX_ITERATIONS tool calls per turn, one call per iteration, each
executed server-side against the caller's visible scope.

Read-only by construction:
  - the 5 grounding bundles ride the ONE tenant_scoped seam
    (app/services/grounding.get_bundle);
  - the narrow record fetches filter through tenant_scoped() and validate
    any explicit project_id against the caller's resolved scope — an arg
    naming a project outside it (another tenant's) returns an error record,
    never data;
  - run_tool NEVER writes and never raises through: any failure (unknown
    tool, malformed args, out-of-scope project) returns an error dict the
    loop turns into the existing degraded fallback.

Tools return COMPACT RECORDS (records-not-prose, like the bundles): every
record carries entity_type/entity_id/title so answers cite real records and
the citation validator can deep-link them.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models.release import Release
from app.models.user_task import UserTask
from app.services import grounding
from app.services.scope import tenant_scoped

# The escalation cap: max tool calls per reasoned turn (one per iteration).
# Overrun → the existing degraded fallback, never an unbounded loop.
TOOL_LOOP_MAX_ITERATIONS = 3

# Records per tool result — compact, not the full table.
MAX_TOOL_RECORDS = 50


def _bundle_tool(name: str):
    """One of the 5 grounding bundles as a tool — the same deterministic
    compute (tenant-scoped, records-not-prose)."""
    def _run(db: Session, user, tenant, args: dict, project_ids: list[int]) -> dict:
        bundle = grounding.get_bundle(db, name, user, tenant, project_ids)
        return {
            "tool": name,
            "records": bundle.get("records") or [],
            "counts": bundle.get("counts") or {},
        }
    return _run


def _arg_scope(args: dict, project_ids: list[int]):
    """The project ids a tool may read: the caller's visible scope, narrowed
    by an explicit project_id arg — which must BE in that scope.

    Returns (project_ids, None) or (None, error). The out-of-scope check is
    the tenant-isolation tightening point: a cross-tenant id never reads."""
    pid = args.get("project_id")
    if pid is None or pid == "":
        return list(project_ids), None
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None, "project_id must be an integer"
    if pid not in project_ids:
        return None, "project not in your visible scope"
    return [pid], None


def _overdue_items(db: Session, user, tenant, args: dict, project_ids: list[int]) -> dict:
    """Overdue tasks for the scope (or one project) — narrow record fetch."""
    scope, err = _arg_scope(args, project_ids)
    if err:
        return {"tool": "overdue_items", "error": err}
    today = date.today()
    q = tenant_scoped(db, UserTask, tenant.id).filter(
        UserTask.status.in_(grounding.OVERDUE_STATUSES),
        UserTask.due_date < today,
        UserTask.project_id.in_(scope),
    )
    rows = q.order_by(UserTask.due_date).limit(MAX_TOOL_RECORDS).all()
    records = [
        {
            "entity_type": "user_task", "entity_id": t.id, "title": t.title,
            "status": t.status, "due_date": str(t.due_date),
            "days_overdue": (today - t.due_date).days,
            "project_id": t.project_id, "assigned_to": t.assigned_to,
        }
        for t in rows
    ]
    return {"tool": "overdue_items", "records": records,
            "counts": {"overdue_items": len(records)}}


def _project_releases(db: Session, user, tenant, args: dict, project_ids: list[int]) -> dict:
    """Releases for the scope (or one project) with status + target dates."""
    scope, err = _arg_scope(args, project_ids)
    if err:
        return {"tool": "project_releases", "error": err}
    q = tenant_scoped(db, Release, tenant.id).filter(Release.project_id.in_(scope))
    rows = q.order_by(Release.id).limit(MAX_TOOL_RECORDS).all()
    records = [
        {
            "entity_type": "release", "entity_id": r.id, "title": r.name,
            "version": r.version, "status": r.status,
            "target_date": r.target_date, "project_id": r.project_id,
        }
        for r in rows
    ]
    return {"tool": "project_releases", "records": records,
            "counts": {"releases": len(records)}}


REGISTRY = {
    "project_health": {
        "description": "Project identity, per-project schedule (CPM critical "
                       "path, release drift), aging items, overdue tasks, "
                       "predictive flags.",
        "args": {},
        "run": _bundle_tool("project_health"),
    },
    "release_readiness": {
        "description": "Gate deliverables, pending approvals, incomplete "
                       "release items, plan-vs-target release drift.",
        "args": {},
        "run": _bundle_tool("release_readiness"),
    },
    "risk_exposure": {
        "description": "Every open risk with severity, probability and score.",
        "args": {},
        "run": _bundle_tool("risk_exposure"),
    },
    "stakeholder_map": {
        "description": "Stakeholders with RACI roles per project.",
        "args": {},
        "run": _bundle_tool("stakeholder_map"),
    },
    "backlog_shape": {
        "description": "Backlog shape: epic → feature counts.",
        "args": {},
        "run": _bundle_tool("backlog_shape"),
    },
    "overdue_items": {
        "description": "Overdue tasks with due dates, days overdue and "
                       "assignee — the narrow per-project fetch.",
        "args": {"project_id": "optional int — one project"},
        "run": _overdue_items,
    },
    "project_releases": {
        "description": "Releases for the scope with status, version and "
                       "target dates — the narrow per-project fetch.",
        "args": {"project_id": "optional int — one project"},
        "run": _project_releases,
    },
}


def run_tool(db: Session, user, tenant, name: str, args, project_ids: list[int]) -> dict:
    """Execute one registry tool. Never raises, never writes: any failure
    (unknown tool, malformed args, out-of-scope project) returns an error
    record — the caller degrades instead of feeding the writer garbage."""
    spec = REGISTRY.get((name or "").strip())
    if spec is None:
        return {"tool": name, "error": f"unknown tool: {name}"}
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {"tool": name, "error": "args must be a JSON object"}
    try:
        scope, err = _arg_scope(args, project_ids)
        if err:
            return {"tool": name, "error": err}
        return spec["run"](db, user, tenant, args, scope)
    except Exception as exc:  # noqa: BLE001 — a tool error must never 500 the loop
        return {"tool": name, "error": str(exc)[:200]}


def tool_registry_prompt() -> str:
    """Compact registry lines for the writer's prompt — what it may call."""
    lines = [
        "AVAILABLE TOOLS (read-only, max 3 per turn) — to pull records the "
        'data above lacks, reply ONLY with {"tool": "<name>", "args": {...}}; '
        "otherwise reply with the answer JSON:",
    ]
    for name, spec in REGISTRY.items():
        args = ", ".join(f"{k} (optional int)" for k in spec["args"]) or "none"
        lines.append(f'- {name}: {spec["description"]} args: {args}')
    return "\n".join(lines)
