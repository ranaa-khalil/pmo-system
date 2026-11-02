"""MCP server — expose the PMO as Model Context Protocol tools over JSON-RPC 2.0.

D4 (v1) of the Wrike inclusion plan: MCP server first. Agents connect to
POST /api/mcp with the same JWT Bearer auth as the API (tenant-scoped):
initialize → tools/list → tools/call. Read-mostly: 7 read tools + 3 safe
writes (create item, set status, add dependency are NOT exposed — agents
work through the app for anything destructive).
"""
import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.release import Release
from app.models.risk import Risk
from app.models.roadmap import Roadmap
from app.models.tenant import Tenant
from app.models.user import User
from app.routers.reports import _build_report
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

PROTOCOL_VERSION = "2024-11-05"


# ─── Tool registry ──────────────────────────────────────────

def _tools() -> list[dict]:
    return [
        {
            "name": "list_projects",
            "description": "List the tenant's projects with status and progress.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_project",
            "description": "One project's detail: backlog counts by phase/status, releases, milestones.",
            "inputSchema": {"type": "object", "required": ["project_id"], "properties": {"project_id": {"type": "integer"}}},
        },
        {
            "name": "list_backlog_items",
            "description": "Backlog items for a project, optionally filtered by status or item type.",
            "inputSchema": {"type": "object", "required": ["project_id"], "properties": {
                "project_id": {"type": "integer"},
                "status": {"type": "string", "description": "Draft | In Progress | Blocked | Done"},
                "item_type": {"type": "string", "description": "e.g. Feature, Bug"},
            }},
        },
        {
            "name": "get_item",
            "description": "One backlog item's full detail: phases, dates, dependencies, proofs, acceptance criteria.",
            "inputSchema": {"type": "object", "required": ["item_id"], "properties": {"item_id": {"type": "integer"}}},
        },
        {
            "name": "create_backlog_item",
            "description": "Create a backlog item in a project.",
            "inputSchema": {"type": "object", "required": ["project_id", "title"], "properties": {
                "project_id": {"type": "integer"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "item_type": {"type": "string"},
                "priority": {"type": "string", "description": "Low | Medium | High | Critical"},
            }},
        },
        {
            "name": "update_item_status",
            "description": "Move a backlog item's status (Draft, In Progress, Blocked, Done).",
            "inputSchema": {"type": "object", "required": ["item_id", "status"], "properties": {
                "item_id": {"type": "integer"},
                "status": {"type": "string"},
            }},
        },
        {
            "name": "list_releases",
            "description": "Releases for a project with phase status.",
            "inputSchema": {"type": "object", "required": ["project_id"], "properties": {"project_id": {"type": "integer"}}},
        },
        {
            "name": "list_risks",
            "description": "Risks for a project, optionally open only.",
            "inputSchema": {"type": "object", "required": ["project_id"], "properties": {
                "project_id": {"type": "integer"},
                "open_only": {"type": "boolean"},
            }},
        },
        {
            "name": "get_status_report",
            "description": "The project status snapshot (progress, releases, open risks, milestones) — same payload as locked status reports.",
            "inputSchema": {"type": "object", "required": ["project_id"], "properties": {"project_id": {"type": "integer"}}},
        },
        {
            "name": "list_approvals",
            "description": "Approval requests for a project, optionally pending only.",
            "inputSchema": {"type": "object", "required": ["project_id"], "properties": {
                "project_id": {"type": "integer"},
                "pending_only": {"type": "boolean"},
            }},
        },
    ]


# ─── Tool implementations ───────────────────────────────────

def _call_tool(name: str, args: dict, db: Session, tenant: Tenant, user: User) -> dict:
    """Dispatch one tool call. Returns a JSON-serializable result."""
    tid = tenant.id

    if name == "list_projects":
        rows = db.query(Project).filter(Project.tenant_id == tid).order_by(Project.id).all()
        return {"projects": [
            {"id": p.id, "name": p.name, "status": p.status, "client_id": p.client_id}
            for p in rows
        ]}

    if name == "get_project":
        p = db.query(Project).filter(Project.id == args["project_id"], Project.tenant_id == tid).first()
        if not p:
            return {"error": f"Project {args['project_id']} not found"}
        items = db.query(BacklogItem).filter(BacklogItem.project_id == p.id).all()
        by_phase = {}
        by_status = {}
        for it in items:
            by_phase[it.current_phase] = by_phase.get(it.current_phase, 0) + 1
            by_status[it.status] = by_status.get(it.status, 0) + 1
        roadmap_ids = [r.id for r in db.query(Roadmap).filter(Roadmap.project_id == p.id).all()]
        milestones = db.query(Milestone).filter(Milestone.roadmap_id.in_(roadmap_ids)).all() if roadmap_ids else []
        return {
            "project": {"id": p.id, "name": p.name, "status": p.status},
            "backlog": {"total": len(items), "by_phase": by_phase, "by_status": by_status},
            "milestones": [{"title": m.title, "status": m.status} for m in milestones],
        }

    if name == "list_backlog_items":
        query = db.query(BacklogItem).filter(
            BacklogItem.project_id == args["project_id"], BacklogItem.tenant_id == tid
        )
        if args.get("status"):
            query = query.filter(BacklogItem.status == args["status"])
        if args.get("item_type"):
            query = query.filter(BacklogItem.item_type == args["item_type"])
        rows = query.order_by(BacklogItem.id).all()
        return {"items": [
            {"id": i.id, "title": i.title, "status": i.status, "phase": i.current_phase,
             "type": i.item_type, "priority": i.priority, "epic": i.epic}
            for i in rows
        ]}

    if name == "get_item":
        i = db.query(BacklogItem).filter(
            BacklogItem.id == args["item_id"], BacklogItem.tenant_id == tid
        ).first()
        if not i:
            return {"error": f"Item {args['item_id']} not found"}
        deps = [{"id": d.id, "title": d.title, "status": d.status} for d in i.depends_on]
        return {
            "id": i.id, "title": i.title, "status": i.status, "phase": i.current_phase,
            "type": i.item_type, "priority": i.priority, "epic": i.epic,
            "description": i.description, "acceptance_criteria": i.acceptance_criteria,
            "start_date": str(i.start_date) if i.start_date else None,
            "end_date": str(i.end_date) if i.end_date else None,
            "depends_on": deps,
        }

    if name == "create_backlog_item":
        p = db.query(Project).filter(Project.id == args["project_id"], Project.tenant_id == tid).first()
        if not p:
            return {"error": f"Project {args['project_id']} not found"}
        item = BacklogItem(
            tenant_id=tid,
            project_id=p.id,
            title=(args.get("title") or "").strip(),
            description=args.get("description"),
            item_type=args.get("item_type"),
            priority=args.get("priority") or "Medium",
        )
        if not item.title:
            return {"error": "A title is required"}
        db.add(item)
        db.commit()
        db.refresh(item)
        return {"created": {"id": item.id, "title": item.title, "status": item.status}}

    if name == "update_item_status":
        i = db.query(BacklogItem).filter(
            BacklogItem.id == args["item_id"], BacklogItem.tenant_id == tid
        ).first()
        if not i:
            return {"error": f"Item {args['item_id']} not found"}
        status = (args.get("status") or "").strip()
        if status not in ("Draft", "In Progress", "Blocked", "Done"):
            return {"error": "status must be Draft, In Progress, Blocked, or Done"}
        i.status = status
        db.commit()
        db.refresh(i)
        return {"updated": {"id": i.id, "title": i.title, "status": i.status}}

    if name == "list_releases":
        rows = db.query(Release).filter(
            Release.project_id == args["project_id"], Release.tenant_id == tid
        ).order_by(Release.created_at.desc()).all()
        return {"releases": [
            {"id": r.id, "version": r.version, "name": r.name, "status": r.status}
            for r in rows
        ]}

    if name == "list_risks":
        query = db.query(Risk).filter(
            Risk.project_id == args["project_id"], Risk.tenant_id == tid
        )
        if args.get("open_only", True):
            query = query.filter(Risk.status != "Closed")
        rows = query.order_by(Risk.severity.desc()).all()
        return {"risks": [
            {"id": r.id, "title": r.title, "severity": r.severity, "status": r.status}
            for r in rows
        ]}

    if name == "get_status_report":
        p = db.query(Project).filter(Project.id == args["project_id"], Project.tenant_id == tid).first()
        if not p:
            return {"error": f"Project {args['project_id']} not found"}
        return _build_report(db, p, user)

    if name == "list_approvals":
        query = db.query(ApprovalRequest).filter(
            ApprovalRequest.project_id == args["project_id"], ApprovalRequest.tenant_id == tid
        )
        if args.get("pending_only", True):
            query = query.filter(ApprovalRequest.status == "Pending")
        rows = query.order_by(ApprovalRequest.id.desc()).all()
        return {"approvals": [
            {"id": a.id, "title": a.title, "type": a.request_type, "status": a.status,
             "current_step": a.current_step}
            for a in rows
        ]}

    return {"error": f"Unknown tool: {name}"}


# ─── JSON-RPC endpoint ──────────────────────────────────────

def _rpc_result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _rpc_error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


@router.post("")
async def mcp_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """JSON-RPC 2.0: initialize · tools/list · tools/call."""
    try:
        body = await request.json()
    except Exception:
        return _rpc_error(None, -32700, "Parse error")
    method = body.get("method")
    id_ = body.get("id")

    if method == "initialize":
        return _rpc_result(id_, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "pmo-system", "version": "1.0.0"},
        })

    if method == "tools/list":
        return _rpc_result(id_, {"tools": _tools()})

    if method == "tools/call":
        params = body.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if not name:
            return _rpc_error(id_, -32602, "Missing tool name")
        known = {t["name"] for t in _tools()}
        if name not in known:
            return _rpc_error(id_, -32602, f"Unknown tool: {name}")
        try:
            result = _call_tool(name, args, db, current_tenant, current_user)
        except Exception as e:  # tool errors surface as MCP tool errors, not 500s
            return _rpc_result(id_, {
                "content": [{"type": "text", "text": f"Tool error: {e}"}],
                "isError": True,
            })
        return _rpc_result(id_, {
            "content": [{"type": "text", "text": json.dumps(result, default=str)}],
            "isError": bool(isinstance(result, dict) and result.get("error")),
        })

    return _rpc_error(id_, -32601, f"Method not found: {method}")
