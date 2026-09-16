"""Dashboard API router — aggregated stats with charts data.

Filters all stats by the user's assigned clients and projects.
A user sees only data for:
  - Clients where they are the account_manager
  - Projects where they are the project_manager or have a RACI role assignment
  - Backlog, KPIs, releases, milestones, approvals for those projects only
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.form_template import FormInstance
from app.models.kpi import KPI
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.release import Release, ReleaseItem
from app.models.roadmap import Roadmap
from app.models.role_assignment import RoleAssignment
from app.models.stakeholder import Stakeholder
from app.models.tenant import Tenant
from app.models.user import User
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get aggregated dashboard statistics with chart data.

    Stats are filtered to only show clients and projects the current user
    is assigned to (as account_manager, project_manager, or RACI role holder).
    """
    tid = current_tenant.id
    uid = current_user.id

    # ── Determine the user's assigned clients and projects ──────────────
    # Projects where the user is PM or has a role assignment
    pm_project_ids = db.query(Project.id).filter(
        Project.tenant_id == tid,
        Project.project_manager_id == uid,
    ).all()
    ra_project_ids = db.query(RoleAssignment.project_id).filter(
        RoleAssignment.user_id == uid,
    ).all()
    assigned_project_ids = set()
    for row in pm_project_ids:
        assigned_project_ids.add(row[0])
    for row in ra_project_ids:
        # Only include projects in this tenant
        p = db.query(Project).filter(Project.id == row[0], Project.tenant_id == tid).first()
        if p:
            assigned_project_ids.add(row[0])

    # Clients where the user is AM, or clients of assigned projects
    am_client_ids = db.query(Client.id).filter(
        Client.tenant_id == tid,
        Client.account_manager_id == uid,
    ).all()
    assigned_client_ids = set(row[0] for row in am_client_ids)
    for pid in assigned_project_ids:
        proj = db.query(Project).filter(Project.id == pid).first()
        if proj and proj.client_id:
            assigned_client_ids.add(proj.client_id)

    # Convert to lists for query filtering (empty = show nothing)
    proj_ids = list(assigned_project_ids) if assigned_project_ids else [0]  # [0] = no results
    client_ids = list(assigned_client_ids) if assigned_client_ids else [0]

    # ── Counts (filtered by user's assignments) ─────────────────────────
    # Note: child records (backlog, kpis, etc.) are filtered by project_id only,
    # since the project_ids are already tenant-scoped above.
    clients_count = db.query(Client).filter(
        Client.tenant_id == tid, Client.id.in_(client_ids),
    ).count()
    projects_count = db.query(Project).filter(
        Project.tenant_id == tid, Project.id.in_(proj_ids),
    ).count()
    backlog_count = db.query(BacklogItem).filter(
        BacklogItem.project_id.in_(proj_ids),
    ).count()
    pending_approvals = db.query(ApprovalRequest).filter(
        ApprovalRequest.status == "Pending",
        ApprovalRequest.project_id.in_(proj_ids),
    ).count()
    forms_count = db.query(FormInstance).filter(
        FormInstance.project_id.in_(proj_ids),
    ).count()
    kpis_count = db.query(KPI).filter(
        KPI.project_id.in_(proj_ids),
    ).count()
    releases_count = db.query(Release).filter(
        Release.project_id.in_(proj_ids),
    ).count()
    stakeholders_count = db.query(Stakeholder).filter(
        Stakeholder.project_id.in_(proj_ids),
    ).count()

    # ── Backlog distributions (filtered) ────────────────────────────────
    items = db.query(BacklogItem).filter(
        BacklogItem.project_id.in_(proj_ids),
    ).all()

    phase_distribution: dict[str, int] = {}
    for item in items:
        phase_distribution[item.current_phase] = phase_distribution.get(item.current_phase, 0) + 1

    status_distribution: dict[str, int] = {}
    for item in items:
        status_distribution[item.status] = status_distribution.get(item.status, 0) + 1

    priority_distribution: dict[str, int] = {}
    for item in items:
        priority_distribution[item.priority] = priority_distribution.get(item.priority, 0) + 1

    # ── Release status distribution (filtered) ──────────────────────────
    releases = db.query(Release).filter(
        Release.tenant_id == tid, Release.project_id.in_(proj_ids),
    ).all()
    release_status_dist: dict[str, int] = {}
    for rel in releases:
        release_status_dist[rel.status] = release_status_dist.get(rel.status, 0) + 1

    # Release items progress
    total_release_items = 0
    completed_release_items = 0
    done_phases = ["Pre-Release", "Release", "Post-Release", "Retrospective"]
    for rel in releases:
        rel_items = db.query(ReleaseItem).filter(
            ReleaseItem.release_id == rel.id,
        ).all()
        for ri in rel_items:
            bi = db.query(BacklogItem).filter(
                BacklogItem.id == ri.backlog_item_id,
            ).first()
            if bi:
                total_release_items += 1
                if bi.current_phase in done_phases:
                    completed_release_items += 1

    # ── Per-project progress (only assigned projects) ───────────────────
    project_progress = []
    all_projects = db.query(Project).filter(
        Project.tenant_id == tid, Project.id.in_(proj_ids),
    ).all()
    for p in all_projects:
        p_backlog = db.query(BacklogItem).filter(
            BacklogItem.project_id == p.id,
        ).all()
        p_releases = db.query(Release).filter(
            Release.project_id == p.id,
        ).all()
        p_kpis = db.query(KPI).filter(
            KPI.project_id == p.id,
        ).all()
        p_stakeholders = db.query(Stakeholder).filter(
            Stakeholder.project_id == p.id,
        ).count()
        p_done = len([i for i in p_backlog if i.current_phase in done_phases])
        p_total = len(p_backlog)
        progress_pct = round((p_done / p_total * 100) if p_total > 0 else 0)

        client = db.query(Client).filter(Client.id == p.client_id, Client.tenant_id == tid).first()
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

    # ── Upcoming milestones (only for assigned projects) ────────────────
    assigned_roadmap_ids = db.query(Roadmap.id).filter(
        Roadmap.project_id.in_(proj_ids),
    ).all()
    roadmap_ids = [r[0] for r in assigned_roadmap_ids] if assigned_roadmap_ids else [0]

    all_milestones = db.query(Milestone).filter(
        Milestone.roadmap_id.in_(roadmap_ids),
    ).all()
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

    # ── Recent projects (only assigned) ─────────────────────────────────
    recent_projects_data = [
        {
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "github_repo": p.github_repo,
            "client_id": p.client_id,
            "client_name": next((pp["client_name"] for pp in project_progress if pp["id"] == p.id), "—"),
        }
        for p in db.query(Project).filter(
            Project.tenant_id == tid, Project.id.in_(proj_ids),
        ).order_by(Project.created_at.desc()).limit(5).all()
    ]

    # ── Pending approvals (only for assigned projects) ──────────────────
    pending = db.query(ApprovalRequest).filter(
        ApprovalRequest.status == "Pending",
        ApprovalRequest.project_id.in_(proj_ids),
    ).limit(5).all()
    pending_data = []
    for a in pending:
        steps = db.query(ApprovalStep).filter(
            ApprovalStep.request_id == a.id,
        ).order_by(ApprovalStep.step_order).all()
        p = db.query(Project).filter(Project.id == a.project_id, Project.tenant_id == tid).first()
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

    # ── KPI progress (only for assigned projects) ───────────────────────
    kpi_progress = []
    for kpi in db.query(KPI).filter(
        KPI.project_id.in_(proj_ids),
    ).all():
        p = db.query(Project).filter(Project.id == kpi.project_id, Project.tenant_id == tid).first()
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
