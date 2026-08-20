"""Dashboard API router — aggregated stats with charts data."""
from typing import Dict, List, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.client import Client
from app.models.project import Project
from app.models.backlog_item import BacklogItem
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.form_template import FormInstance
from app.models.kpi import KPI
from app.models.release import Release, ReleaseItem
from app.models.milestone import Milestone
from app.models.roadmap import Roadmap
from app.models.stakeholder import Stakeholder

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get aggregated dashboard statistics with chart data."""
    # Counts
    clients_count = db.query(Client).count()
    projects_count = db.query(Project).count()
    backlog_count = db.query(BacklogItem).count()
    pending_approvals = db.query(ApprovalRequest).filter(ApprovalRequest.status == "Pending").count()
    forms_count = db.query(FormInstance).count()
    kpis_count = db.query(KPI).count()
    releases_count = db.query(Release).count()
    stakeholders_count = db.query(Stakeholder).count()

    # Backlog phase distribution
    phase_distribution: Dict[str, int] = {}
    items = db.query(BacklogItem).all()
    for item in items:
        phase_distribution[item.current_phase] = phase_distribution.get(item.current_phase, 0) + 1

    # Backlog status distribution
    status_distribution: Dict[str, int] = {}
    for item in items:
        status_distribution[item.status] = status_distribution.get(item.status, 0) + 1

    # Backlog priority distribution
    priority_distribution: Dict[str, int] = {}
    for item in items:
        priority_distribution[item.priority] = priority_distribution.get(item.priority, 0) + 1

    # Release status distribution (for donut chart)
    release_status_dist: Dict[str, int] = {}
    releases = db.query(Release).all()
    for rel in releases:
        release_status_dist[rel.status] = release_status_dist.get(rel.status, 0) + 1

    # Release items progress
    total_release_items = 0
    completed_release_items = 0
    done_phases = ["Pre-Release", "Release", "Post-Release", "Retrospective"]
    for rel in releases:
        rel_items = db.query(ReleaseItem).filter(ReleaseItem.release_id == rel.id).all()
        for ri in rel_items:
            bi = db.query(BacklogItem).filter(BacklogItem.id == ri.backlog_item_id).first()
            if bi:
                total_release_items += 1
                if bi.current_phase in done_phases:
                    completed_release_items += 1

    # Per-project progress
    project_progress = []
    all_projects = db.query(Project).all()
    for p in all_projects:
        p_backlog = db.query(BacklogItem).filter(BacklogItem.project_id == p.id).all()
        p_releases = db.query(Release).filter(Release.project_id == p.id).all()
        p_kpis = db.query(KPI).filter(KPI.project_id == p.id).all()
        p_stakeholders = db.query(Stakeholder).filter(Stakeholder.project_id == p.id).count()
        p_done = len([i for i in p_backlog if i.current_phase in done_phases])
        p_total = len(p_backlog)
        progress_pct = round((p_done / p_total * 100) if p_total > 0 else 0)

        # Client name
        client = db.query(Client).filter(Client.id == p.client_id).first()
        client_name = client.name if client else "—"

        project_progress.append({
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "client_name": client_name,
            "backlog_total": p_total,
            "backlog_done": p_done,
            "progress_pct": progress_pct,
            "releases_count": len(p_releases),
            "kpis_count": len(p_kpis),
            "stakeholders_count": p_stakeholders,
        })

    # Upcoming milestones (next 5 by target_date)
    all_milestones = db.query(Milestone).all()
    upcoming_milestones = []
    for ms in all_milestones:
        if ms.status != "Completed":
            rm = db.query(Roadmap).filter(Roadmap.id == ms.roadmap_id).first()
            if rm:
                p = db.query(Project).filter(Project.id == rm.project_id).first()
                upcoming_milestones.append({
                    "id": ms.id,
                    "title": ms.title,
                    "target_date": str(ms.target_date) if ms.target_date else None,
                    "status": ms.status,
                    "project_name": p.name if p else "—",
                    "project_id": p.id if p else None,
                })
    upcoming_milestones.sort(key=lambda x: x.get("target_date") or "9999")
    upcoming_milestones = upcoming_milestones[:5]

    # Recent projects
    recent_projects_data = [
        {
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "github_repo": p.github_repo,
            "client_id": p.client_id,
            "client_name": next((pp["client_name"] for pp in project_progress if pp["id"] == p.id), "—"),
        }
        for p in db.query(Project).order_by(Project.created_at.desc()).limit(5).all()
    ]

    # Pending approvals with details
    pending = db.query(ApprovalRequest).filter(ApprovalRequest.status == "Pending").limit(5).all()
    pending_data = []
    for a in pending:
        steps = db.query(ApprovalStep).filter(ApprovalStep.approval_request_id == a.id).order_by(ApprovalStep.step_order).all()
        p = db.query(Project).filter(Project.id == a.project_id).first()
        pending_data.append({
            "id": a.id,
            "title": a.title,
            "request_type": a.request_type,
            "current_step": a.current_step,
            "project_id": a.project_id,
            "project_name": p.name if p else "—",
            "total_steps": len(steps),
            "approved_steps": len([s for s in steps if s.status == "Approved"]),
        })

    # KPI progress summary (for gauge)
    kpi_progress = []
    for kpi in db.query(KPI).all():
        p = db.query(Project).filter(Project.id == kpi.project_id).first()
        kpi_progress.append({
            "id": kpi.id,
            "name": kpi.name,
            "target_value": kpi.target_value,
            "current_value": kpi.current_value,
            "unit": kpi.unit,
            "project_name": p.name if p else "—",
        })

    return {
        "clients": clients_count,
        "projects": projects_count,
        "backlog_items": backlog_count,
        "pending_approvals": pending_approvals,
        "forms": forms_count,
        "kpis": kpis_count,
        "releases": releases_count,
        "stakeholders": stakeholders_count,
        "phase_distribution": phase_distribution,
        "status_distribution": status_distribution,
        "priority_distribution": priority_distribution,
        "release_status_distribution": release_status_dist,
        "total_release_items": total_release_items,
        "completed_release_items": completed_release_items,
        "project_progress": project_progress,
        "upcoming_milestones": upcoming_milestones,
        "recent_projects": recent_projects_data,
        "pending_approval_details": pending_data,
        "kpi_progress": kpi_progress,
    }
