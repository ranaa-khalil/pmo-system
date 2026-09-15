"""Analytics router — advanced project metrics for business PMO."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.services.analytics_service import (
    burndown_data,
    cycle_time,
    cumulative_flow,
    kpi_trend,
    phase_distribution,
    project_analytics_summary,
    velocity_per_release,
)
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/projects/{project_id}/analytics")
def get_project_analytics(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get complete analytics summary for a project."""
    from fastapi import HTTPException
    project = db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant.id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project_analytics_summary(db, current_tenant.id, project_id)


@router.get("/projects/{project_id}/analytics/velocity")
def get_velocity(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Items completed per release (velocity)."""
    from fastapi import HTTPException
    if not db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant.id).first():
        raise HTTPException(404, "Project not found")
    return velocity_per_release(db, current_tenant.id, project_id)


@router.get("/releases/{release_id}/analytics/burndown")
def get_burndown(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Burndown data for a release."""
    return burndown_data(db, current_tenant.id, release_id)


@router.get("/projects/{project_id}/analytics/cycle-time")
def get_cycle_time(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Average cycle time (creation to Ready for UAT)."""
    return cycle_time(db, current_tenant.id, project_id)


@router.get("/projects/{project_id}/analytics/cumulative-flow")
def get_cumulative_flow(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Cumulative flow diagram data."""
    return cumulative_flow(db, current_tenant.id, project_id)


@router.get("/projects/{project_id}/analytics/phase-distribution")
def get_phase_distribution(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Current backlog items by phase."""
    return phase_distribution(db, current_tenant.id, project_id)


@router.get("/projects/{project_id}/analytics/kpi-trend")
def get_kpi_trend(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """KPI values and progress."""
    return kpi_trend(db, current_tenant.id, project_id)
