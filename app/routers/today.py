"""Today + Work API — the R1 spine.

GET /api/today — needs-you aggregate + briefing for the current user's tenant.
GET /api/work — unified cross-project work list with filter chips.
GET /api/projects/{project_id}/brief — narrative from live data.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.services.tenant import get_current_tenant
from app.services.today import build_brief, build_today

router = APIRouter(prefix="/api", tags=["today"])


@router.get("/today")
def today_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """The needs-you aggregate: approvals on your gates, blocked, overdue, escalated."""
    return build_today(db, current_tenant, current_user)


@router.get("/work")
def work_endpoint(
    filter: str = "all",
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Unified cross-project work list: one list, filter chips instead of tabs."""
    projects = db.query(Project).filter(Project.tenant_id == current_tenant.id).all()
    project_ids = [p.id for p in projects]
    names = {p.id: p.name for p in projects}
    q = db.query(BacklogItem)
    if project_ids:
        q = q.filter(BacklogItem.project_id.in_(project_ids))
    if project_id:
        q = q.filter(BacklogItem.project_id == project_id)
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
    return {
        "items": [
            {
                "id": it.id,
                "title": it.title,
                "project_id": it.project_id,
                "project": names.get(it.project_id, ""),
                "phase": it.current_phase,
                "status": it.status,
                "priority": it.priority,
                "assigned_to": it.assigned_to,
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
    }


@router.get("/projects/{project_id}/brief")
def brief_endpoint(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Narrative brief from live data (template v0; nightly AI rewrite lands in R3)."""
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.tenant_id == current_tenant.id)
        .first()
    )
    if not project:
        from fastapi import HTTPException

        raise HTTPException(404, "Project not found in this tenant.")
    return build_brief(db, project)


def _current_month() -> str:
    from datetime import date

    return date.today().strftime("%Y-%m")
