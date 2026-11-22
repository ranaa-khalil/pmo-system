"""Dashboard stats — Rethink v2 Phase F2.

The router's get_dashboard_stats moved here and its 33+ sequential queries
(with six N+1 loops: per-RoleAssignment tenant checks, per-project
backlog/releases/KPIs/stakeholders/client lookups, per-release item walks,
per-milestone roadmap/project lookups, per-pending-approval step/project
lookups) are rewritten as flat grouped queries bucketed in Python — the
compute_coverage pattern (one IN-query, bucketed in Python, never N+1).

The payload keys and values are byte-identical to the handler this replaces:
same assignment logic (PM projects + RACI role assignments, tenant-checked;
AM clients + assigned projects' clients), same counts, same distributions,
same done_phases, same progress math (round()), same sort + 5-item slices.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

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

# The "done" phases (byte-identical to the handler this replaces).
DONE_PHASES = ["Pre-Release", "Release", "Post-Release", "Retrospective"]


def get_dashboard_stats(db: Session, current_user: User, current_tenant: Tenant) -> dict:
    """Aggregated dashboard statistics with chart data.

    Stats are filtered to only show clients and projects the current user
    is assigned to (as account_manager, project_manager, or RACI role holder).
    """
    tid = current_tenant.id
    uid = current_user.id

    # ── Determine the user's assigned clients and projects ──────────────
    # One tenant-wide project fetch replaces the per-RA and per-project
    # tenant-check N+1 loops: the RA ids are tenant-checked by set
    # membership, and the client mapping reads the same rows.
    projects = db.query(Project).filter(Project.tenant_id == tid).all()
    projects_by_id = {p.id: p for p in projects}

    pm_project_ids = {p.id for p in projects if p.project_manager_id == uid}
    ra_project_ids = {
        row[0]
        for row in db.query(RoleAssignment.project_id)
        .filter(RoleAssignment.user_id == uid)
        .all()
    }
    # Only include RA projects in this tenant (same check the per-id loop did)
    assigned_project_ids = pm_project_ids | (ra_project_ids & set(projects_by_id))

    # Clients where the user is AM, or clients of assigned projects
    am_client_ids = {
        row[0]
        for row in db.query(Client.id)
        .filter(Client.tenant_id == tid, Client.account_manager_id == uid)
        .all()
    }
    assigned_client_ids = set(am_client_ids)
    for p in projects:
        if p.id in assigned_project_ids and p.client_id:
            assigned_client_ids.add(p.client_id)

    # Convert to lists for query filtering (empty = show nothing)
    proj_ids = list(assigned_project_ids) if assigned_project_ids else [0]  # [0] = no results
    client_ids = list(assigned_client_ids) if assigned_client_ids else [0]

    # ── Clients (count + name map in one query) ─────────────────────────
    client_rows = db.query(Client).filter(
        Client.tenant_id == tid, Client.id.in_(client_ids),
    ).all()
    clients_count = len(client_rows)
    client_names = {c.id: c.name for c in client_rows}

    # ── Backlog: one light-column fetch feeds the count, the three
    #    distributions, and the per-project totals ───────────────────────
    bl_rows = db.query(
        BacklogItem.project_id,
        BacklogItem.current_phase,
        BacklogItem.status,
        BacklogItem.priority,
    ).filter(BacklogItem.project_id.in_(proj_ids)).all()
    backlog_count = len(bl_rows)

    phase_distribution: dict[str, int] = {}
    status_distribution: dict[str, int] = {}
    priority_distribution: dict[str, int] = {}
    bl_by_project: dict[int, list[tuple]] = {}
    for pid, phase, status, priority in bl_rows:
        phase_distribution[phase] = phase_distribution.get(phase, 0) + 1
        status_distribution[status] = status_distribution.get(status, 0) + 1
        priority_distribution[priority] = priority_distribution.get(priority, 0) + 1
        bl_by_project.setdefault(pid, []).append(phase)

    # ── Releases: one fetch feeds the count, the status distribution, and
    #    the per-project rollup ───────────────────────────────────────────
    releases = db.query(Release).filter(
        Release.tenant_id == tid, Release.project_id.in_(proj_ids),
    ).all()
    releases_count = len(releases)
    release_status_dist: dict[str, int] = {}
    releases_by_project: dict[int, int] = {}
    for rel in releases:
        release_status_dist[rel.status] = release_status_dist.get(rel.status, 0) + 1
        releases_by_project[rel.project_id] = releases_by_project.get(rel.project_id, 0) + 1

    # Release items progress: one ReleaseItem fetch + one BacklogItem fetch
    # replaces the per-release × per-item N+1 walk.
    release_ids = [rel.id for rel in releases]
    total_release_items = 0
    completed_release_items = 0
    if release_ids:
        ri_rows = db.query(ReleaseItem.release_id, ReleaseItem.backlog_item_id).filter(
            ReleaseItem.release_id.in_(release_ids),
        ).all()
        bi_ids = {row[1] for row in ri_rows}
        bi_phases = {
            row[0]: row[1]
            for row in db.query(BacklogItem.id, BacklogItem.current_phase)
            .filter(BacklogItem.id.in_(list(bi_ids)))
            .all()
        } if bi_ids else {}
        for _rel_id, bi_id in ri_rows:
            if bi_id in bi_phases:
                total_release_items += 1
                if bi_phases[bi_id] in DONE_PHASES:
                    completed_release_items += 1

    # ── Grouped per-model counts (one grouped query each replaces a count
    #    + a per-project N+1) ─────────────────────────────────────────────
    forms_by_project = dict(
        db.query(FormInstance.project_id, func.count(FormInstance.id))
        .filter(FormInstance.project_id.in_(proj_ids))
        .group_by(FormInstance.project_id)
        .all()
    )
    stakeholders_by_project = dict(
        db.query(Stakeholder.project_id, func.count(Stakeholder.id))
        .filter(Stakeholder.project_id.in_(proj_ids))
        .group_by(Stakeholder.project_id)
        .all()
    )

    # ── KPIs: one fetch feeds the count, the per-project rollup, and the
    #    progress list ────────────────────────────────────────────────────
    kpi_rows = db.query(KPI).filter(KPI.project_id.in_(proj_ids)).all()
    kpis_count = len(kpi_rows)
    kpis_by_project: dict[int, int] = {}
    for k in kpi_rows:
        kpis_by_project[k.project_id] = kpis_by_project.get(k.project_id, 0) + 1

    # ── Per-project progress (only assigned projects) ───────────────────
    project_progress = []
    for p in projects:
        if p.id not in assigned_project_ids:
            continue
        p_bl = bl_by_project.get(p.id, [])
        p_total = len(p_bl)
        p_done = len([phase for phase in p_bl if phase in DONE_PHASES])
        progress_pct = round((p_done / p_total * 100) if p_total > 0 else 0)

        client_name = client_names.get(p.client_id, "—") if p.client_id else "—"

        project_progress.append({
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "client_name": client_name,
            "backlog_total": p_total,
            "backlog_done": p_done,
            "progress_pct": progress_pct,
            "releases_count": releases_by_project.get(p.id, 0),
            "kpis_count": kpis_by_project.get(p.id, 0),
            "stakeholders_count": stakeholders_by_project.get(p.id, 0),
        })

    # ── Upcoming milestones (only for assigned projects) ────────────────
    # One roadmap fetch replaces the ids-query + per-row lookups pair.
    roadmaps_by_id = {
        rm.id: rm
        for rm in db.query(Roadmap).filter(Roadmap.project_id.in_(proj_ids)).all()
    }
    roadmap_ids = list(roadmaps_by_id.keys()) if roadmaps_by_id else [0]
    all_milestones = db.query(Milestone).filter(
        Milestone.roadmap_id.in_(roadmap_ids),
    ).all()
    upcoming_milestones = []
    for ms in all_milestones:
        if ms.status != "Completed":
            rm = roadmaps_by_id.get(ms.roadmap_id)
            if rm:
                p = projects_by_id.get(rm.project_id)
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
    # One fetch replaces the count() + limit(5) pair; the steps and project
    # names come from one IN-fetch and the project map (no per-row lookups).
    pending_rows = db.query(ApprovalRequest).filter(
        ApprovalRequest.status == "Pending",
        ApprovalRequest.project_id.in_(proj_ids),
    ).all()
    pending_approvals = len(pending_rows)
    pending = pending_rows[:5]
    steps_by_request: dict[int, list] = {}
    if pending:
        step_rows = (
            db.query(ApprovalStep)
            .filter(ApprovalStep.request_id.in_([a.id for a in pending]))
            .order_by(ApprovalStep.request_id, ApprovalStep.step_order)
            .all()
        )
        for s in step_rows:
            steps_by_request.setdefault(s.request_id, []).append(s)
    pending_data = []
    for a in pending:
        steps = steps_by_request.get(a.id, [])
        p = projects_by_id.get(a.project_id)
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
    for kpi in kpi_rows:
        p = projects_by_id.get(kpi.project_id)
        kpi_progress.append({
            "id": kpi.id,
            "name": kpi.name,
            "target_value": kpi.target_value,
            "current_value": kpi.current_value,
            "unit": kpi.unit,
            "project_id": kpi.project_id,
            "project_name": p.name if p else "—",
        })

    return {
        "clients": clients_count,
        "projects": len(assigned_project_ids),
        "backlog_items": backlog_count,
        "pending_approvals": pending_approvals,
        "forms": sum(forms_by_project.values()),
        "kpis": kpis_count,
        "releases": releases_count,
        "stakeholders": sum(stakeholders_by_project.values()),
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
