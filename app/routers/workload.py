"""Team workload — per-member open-item counts for the workload strip.

Read-only aggregate over the tenant: open backlog items + open user tasks
per member, sorted by load. No timers, no timesheets — a strip, not surveillance.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_task import UserTask
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["workload"])

_OPEN_ITEM_STATUSES = ["Draft", "In Progress", "Blocked"]
_OPEN_TASK_STATUSES = ["Pending", "In Progress"]


@router.get("/workload")
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
