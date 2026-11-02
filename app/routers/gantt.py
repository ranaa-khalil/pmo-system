"""Project item Gantt API — schedule window + CPM computed on read.

Critical path and float are computed from the EXISTING backlog dependency
graph (backlog_item_dependencies M2M) over items that have both dates.
Float = late_start - early_start; critical = float 0. Items in a dependency
cycle or without dates are reported unscheduled, never guessed.
"""
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem, backlog_dependencies
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["gantt"])


@router.get("/projects/{project_id}/gantt")
def project_gantt(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Item-level Gantt data: scheduled window, dependencies, CPM float/critical."""
    project = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    items = db.query(BacklogItem).filter(BacklogItem.project_id == project_id).all()
    scheduled = {
        it.id: it for it in items
        if it.start_date and it.end_date and it.start_date <= it.end_date
    }
    if not scheduled:
        return {
            "project_id": project_id,
            "start": None,
            "end": None,
            "items": [],
            "unscheduled_count": len(items),
            "critical_count": 0,
        }

    # Dependency edges (only where both ends are scheduled)
    rows = db.query(
        backlog_dependencies.c.dependent_id, backlog_dependencies.c.depends_on_id
    ).filter(
        backlog_dependencies.c.dependent_id.in_(list(scheduled.keys())),
        backlog_dependencies.c.depends_on_id.in_(list(scheduled.keys())),
    ).all()
    deps = {iid: [] for iid in scheduled}      # id -> items it depends on
    blocks = {iid: [] for iid in scheduled}    # id -> items that depend on it
    for dependent_id, depends_on_id in rows:
        deps[dependent_id].append(depends_on_id)
        blocks[depends_on_id].append(dependent_id)

    # Day offsets from the project window start
    window_start = min(it.start_date for it in scheduled.values())
    window_end = max(it.end_date for it in scheduled.values())

    def offset(d: date_type) -> int:
        return (d - window_start).days

    durations = {iid: offset(it.end_date) - offset(it.start_date) + 1 for iid, it in scheduled.items()}  # inclusive days
    durations = {iid: max(dur, 1) for iid, dur in durations.items()}  # min 1 day

    # Kahn topological sort — cycle-safe
    indegree = {iid: len(set(deps[iid])) for iid in scheduled}
    queue = sorted([iid for iid, deg in indegree.items() if deg == 0])
    order = []
    seen_deps = {iid: set(deps[iid]) for iid in scheduled}
    while queue:
        iid = queue.pop(0)
        order.append(iid)
        for nxt in sorted(set(blocks[iid])):
            seen_deps[nxt].discard(iid)
            if not seen_deps[nxt] and nxt not in order:
                queue.append(nxt)
    in_cycle = set(scheduled) - set(order)  # cycle members: no CPM numbers

    # Forward pass: early start/finish
    es = {}
    ef = {}
    for iid in order:
        preds = [ef[p] for p in set(deps[iid]) if p in ef]
        es[iid] = max(preds) if preds else 0
        ef[iid] = es[iid] + durations[iid]
    project_finish = max(ef.values()) if ef else 0

    # Backward pass: late start/finish
    lf = {}
    ls = {}
    for iid in reversed(order):
        succs = [ls[s] for s in set(blocks[iid]) if s in ls]
        lf[iid] = min(succs) if succs else project_finish
        ls[iid] = lf[iid] - durations[iid]

    result_items = []
    critical_count = 0
    for it in items:
        base = {
            "id": it.id,
            "title": it.title,
            "current_phase": it.current_phase,
            "status": it.status,
            "priority": it.priority,
            "epic": it.epic,
            "start_date": str(it.start_date) if it.start_date else None,
            "end_date": str(it.end_date) if it.end_date else None,
            "depends_on": sorted(d.id for d in (it.depends_on or [])),
            "blocks": sorted(blocks.get(it.id, [])),
        }
        if it.id in scheduled and it.id not in in_cycle:
            f = ls[it.id] - es[it.id]
            if f == 0:
                critical_count += 1
            base.update({
                "duration": durations[it.id],
                "early_start": es[it.id],
                "early_finish": ef[it.id],
                "late_start": ls[it.id],
                "late_finish": lf[it.id],
                "float": f,
                "is_critical": f == 0,
            })
        else:
            base.update({"duration": None, "float": None, "is_critical": False})
        result_items.append(base)

    return {
        "project_id": project_id,
        "start": str(window_start),
        "end": str(window_end),
        "total_days": (window_end - window_start).days + 1,
        "items": result_items,
        "unscheduled_count": len(items) - len(scheduled),
        "critical_count": critical_count,
    }
