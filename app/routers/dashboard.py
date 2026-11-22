"""Dashboard API router — aggregated stats with charts data.

The handler moved to app/services/stats.py (Rethink v2 Phase F2 — the
33-query god-handler is now a grouped-aggregate service); this router
delegates in one line. Filters all stats by the user's assigned clients
and projects. A user sees only data for:
  - Clients where they are the account_manager
  - Projects where they are the project_manager or have a RACI role assignment
  - Backlog, KPIs, releases, milestones, approvals for those projects only
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.tenant import Tenant
from app.models.user import User
from app.services import stats as stats_service
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get aggregated dashboard statistics with chart data."""
    return stats_service.get_dashboard_stats(db, current_user, current_tenant)
