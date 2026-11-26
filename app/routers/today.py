"""Today + Work API — the R1 spine.

GET /api/today — needs-you aggregate + briefing for the current user's tenant.
GET /api/work — unified cross-project work list with filter chips.
GET /api/projects/{project_id}/brief — narrative from live data.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.comment import Comment
from app.models.project import Project
from app.models.tag import Tag, backlog_item_tags
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.work import WorkList
from app.services.grounding import drift_radar
from app.services.scope import tenant_scoped
from app.services.tenant import get_current_tenant
from app.services.today import build_brief, build_today

router = APIRouter(prefix="/api", tags=["today"])


@router.get("/today")
def today_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """The needs-you aggregate: approvals on your gates, blocked, overdue, escalated
    + the drift radar (Rethink §3 #3 — per in-flight release, deterministic)."""
    result = build_today(db, current_tenant, current_user)
    # Drift Radar: the Today Brief card's Drift section — deterministic compute
    # (schedule.py's plan-vs-target), rendered without any LLM call.
    result["drift_radar"] = drift_radar(db, current_tenant)
    return result


@router.get("/work", response_model=WorkList)
def work_endpoint(
    filter: str = "all",
    project_id: int | None = None,
    tag_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Unified cross-project work list: one list, filter chips instead of tabs.

    tag_id filters via the cross-tagging M2M (one tag, many items).
    """
    projects = tenant_scoped(db, Project, current_tenant.id).all()
    project_ids = [p.id for p in projects]
    names = {p.id: p.name for p in projects}
    q = db.query(BacklogItem)
    if project_ids:
        q = q.filter(BacklogItem.project_id.in_(project_ids))
    if project_id:
        q = q.filter(BacklogItem.project_id == project_id)
    if tag_id:
        # Validate the tag belongs to this tenant (404 otherwise), then join
        if not tenant_scoped(db, Tag, current_tenant.id).filter(Tag.id == tag_id).first():
            from fastapi import HTTPException

            raise HTTPException(404, "Tag not found in this tenant.")
        q = q.join(backlog_item_tags, BacklogItem.id == backlog_item_tags.c.backlog_item_id).filter(
            backlog_item_tags.c.tag_id == tag_id
        )
    if filter == "blocked":
        q = q.filter(BacklogItem.status == "Blocked")
    elif filter == "mine":
        q = q.filter(BacklogItem.assigned_to == current_user.id)
    elif filter == "overdue":
        month = _current_month()
        q = q.filter(
            BacklogItem.status.in_(("In Progress", "Review")),
            BacklogItem.target_release.isnot(None),
            BacklogItem.target_release < month,
        )
    items = q.order_by(BacklogItem.updated_at.desc()).limit(200).all()
    month = _current_month()
    return {"items": _work_items(db, items, names, month)}


def _work_items(db: Session, items: list[BacklogItem], names: dict[int, str], month: str) -> list[dict]:
    """Build the ONE Work view payload: the 10 R1 columns + the 8 R2 columns.

    The extra columns (item_type, epic, assigned_to_name, tags[], comment_count,
    board_order, start/end dates) all come from existing BacklogItem
    columns/relations — three batched lookups, no per-item queries.
    """
    if not items:
        return []
    ids = [it.id for it in items]

    # Assignee names (assigned_to is a users.id FK — look the names up by id)
    assignee_ids = sorted({it.assigned_to for it in items if it.assigned_to})
    user_names = {}
    if assignee_ids:
        user_names = {
            u.id: u.name
            for u in db.query(User).filter(User.id.in_(assignee_ids)).all()
        }

    # Tags per item (backlog_item_tags M2M — the pool the Work tag filter reads)
    tag_rows = (
        db.query(
            backlog_item_tags.c.backlog_item_id,
            Tag.id,
            Tag.name,
            Tag.color,
        )
        .join(Tag, Tag.id == backlog_item_tags.c.tag_id)
        .filter(backlog_item_tags.c.backlog_item_id.in_(ids))
        .order_by(Tag.name)
        .all()
    )
    tags_by_item: dict[int, list[dict]] = {}
    for item_id, tag_id_, tag_name, tag_color in tag_rows:
        tags_by_item.setdefault(item_id, []).append(
            {"id": tag_id_, "name": tag_name, "color": tag_color}
        )

    # Comment counts (one Comment row per item comment)
    count_rows = (
        db.query(Comment.item_id, func.count(Comment.id))
        .filter(Comment.item_id.in_(ids))
        .group_by(Comment.item_id)
        .all()
    )
    counts = dict(count_rows)

    return [
        {
            "id": it.id,
            "title": it.title,
            "project_id": it.project_id,
            "project": names.get(it.project_id, ""),
            "phase": it.current_phase,
            "status": it.status,
            "priority": it.priority,
            "assigned_to": it.assigned_to,
            "assigned_to_name": user_names.get(it.assigned_to) if it.assigned_to else None,
            "item_type": it.item_type,
            "epic": it.epic,
            "tags": tags_by_item.get(it.id, []),
            "comment_count": counts.get(it.id, 0),
            "board_order": it.board_order,
            "start_date": it.start_date,
            "end_date": it.end_date,
            "target_release": it.target_release,
            "overdue": bool(
                it.status in ("In Progress", "Review")
                and it.target_release
                and it.target_release < month
            ),
            "blocked": it.status == "Blocked",
        }
        for it in items
    ]


@router.get("/projects/{project_id}/brief")
def brief_endpoint(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Narrative brief from live data (template v0; nightly AI rewrite lands in R3)."""
    project = (
        tenant_scoped(db, Project, current_tenant.id)
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        from fastapi import HTTPException

        raise HTTPException(404, "Project not found in this tenant.")
    return build_brief(db, project)


def _current_month() -> str:
    from datetime import date

    return date.today().strftime("%Y-%m")
