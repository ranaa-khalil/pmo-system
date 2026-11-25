"""Dashboard API router — dashboard, team workload, and project Gantt in ONE.

Rethink v2 Phase F3: the dashboard/workload/gantt routers are merged into
this single mounted router. Every route path, method, response shape and
status code is byte-identical to the three routers it replaces (the
frontend and the topbar fetch these URLs); the router prefix (/api) is
preserved and each route keeps its own OpenAPI tag via the per-route
``tags=`` argument — the OpenAPI groups are unchanged.

Routes:
  - GET /api/dashboard — aggregated stats with charts data. The handler
    moved to app/services/stats.py (Rethink v2 Phase F2 — the 33-query
    god-handler is now a grouped-aggregate service); this router delegates
    in one line. Filters all stats by the user's assigned clients and
    projects. A user sees only data for:
      - Clients where they are the account_manager
      - Projects where they are the project_manager or have a RACI role
        assignment
      - Backlog, KPIs, releases, milestones, approvals for those projects
        only
  - GET /api/workload — team workload: per-member open-item counts for the
    workload strip. Read-only aggregate over the tenant: open backlog items
    + open user tasks per member, sorted by load. No timers, no timesheets
    — a strip, not surveillance.
  - GET /api/projects/{project_id}/gantt — project item Gantt: schedule
    window + CPM computed on read. The compute moved to
    app/services/schedule.py (the same service-layer pattern the stats
    handler uses) so the Copilot's schedule-aware ask reads the same
    numbers from one place; this router delegates in one line and the
    response shape is byte-identical.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_task import UserTask
from app.services import schedule as schedule_service
from app.services import stats as stats_service
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api")

_OPEN_ITEM_STATUSES = ["Draft", "In Progress", "Blocked"]
_OPEN_TASK_STATUSES = ["Pending", "In Progress"]


@router.get("/dashboard", tags=["dashboard"])
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get aggregated dashboard statistics with chart data."""
    return stats_service.get_dashboard_stats(db, current_user, current_tenant)


@router.get("/workload", tags=["workload"])
def team_workload(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Per-member open work: backlog items + personal tasks, sorted by load."""
    from app.models.tenant import TenantMembership

    members = db.query(User).join(
        TenantMembership, TenantMembership.user_id == User.id
    ).filter(TenantMembership.tenant_id == current_tenant.id).all()

    result = []
    for member in members:
        open_items = db.query(BacklogItem).filter(
            BacklogItem.assigned_to == member.id,
            BacklogItem.status.in_(_OPEN_ITEM_STATUSES),
            BacklogItem.tenant_id == current_tenant.id,
        ).count()
        open_tasks = db.query(UserTask).filter(
            UserTask.assigned_to == member.id,
            UserTask.status.in_(_OPEN_TASK_STATUSES),
            UserTask.tenant_id == current_tenant.id,
        ).count()
        result.append({
            "user_id": member.id,
            "name": member.name,
            "open_items": open_items,
            "open_tasks": open_tasks,
            "total": open_items + open_tasks,
        })
    return sorted(result, key=lambda r: -r["total"])


@router.get("/projects/{project_id}/gantt", tags=["gantt"])
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
    return schedule_service.project_schedule(
        db, project_id, current_tenant.id, project.project_type
    )
