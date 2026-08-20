"""Dashboard API router — aggregated stats for role-based dashboards."""
from typing import Dict, List, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.client import Client
from app.models.project import Project
from app.models.backlog_item import BacklogItem
from app.models.approval import ApprovalRequest
from app.models.form_template import FormInstance
from app.models.kpi import KPI

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get aggregated dashboard statistics."""
    # Counts
    clients_count = db.query(Client).count()
    projects_count = db.query(Project).count()
    backlog_count = db.query(BacklogItem).count()
    pending_approvals = db.query(ApprovalRequest).filter(ApprovalRequest.status == "Pending").count()
    forms_count = db.query(FormInstance).count()
    kpis_count = db.query(KPI).count()

    # Backlog phase distribution
    phase_distribution: Dict[str, int] = {}
    items = db.query(BacklogItem).all()
    for item in items:
        phase_distribution[item.current_phase] = phase_distribution.get(item.current_phase, 0) + 1

    # Backlog status distribution
    status_distribution: Dict[str, int] = {}
    for item in items:
        status_distribution[item.status] = status_distribution.get(item.status, 0) + 1

    # Recent projects
    recent_projects = db.query(Project).order_by(Project.created_at.desc()).limit(5).all()
    recent_project_data = [
        {
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "github_repo": p.github_repo,
            "client_id": p.client_id,
        }
        for p in recent_projects
    ]

    # Pending approval requests with details
    pending = db.query(ApprovalRequest).filter(ApprovalRequest.status == "Pending").limit(5).all()
    pending_data = [
        {
            "id": a.id,
            "title": a.title,
            "request_type": a.request_type,
            "current_step": a.current_step,
            "project_id": a.project_id,
        }
        for a in pending
    ]

    return {
        "clients": clients_count,
        "projects": projects_count,
        "backlog_items": backlog_count,
        "pending_approvals": pending_approvals,
        "forms": forms_count,
        "kpis": kpis_count,
        "phase_distribution": phase_distribution,
        "status_distribution": status_distribution,
        "recent_projects": recent_project_data,
        "pending_approval_details": pending_data,
    }
