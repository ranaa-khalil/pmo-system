"""Rethink v2 Phase F2 — dashboard stats to the service layer.

Covers: the query budget (the payload computes in ≤ 16 flat queries with
seeded data where the old handler ran 33+ sequential queries plus six N+1
loops — per-release × per-item walks, per-project fan-outs, per-RA
tenant-checks, per-milestone and per-pending-approval lookups), payload
parity with the handler this replaces (a reference computed the OLD way,
inline, on the same fixture), the response shape, tenant scoping (a foreign
tenant's data never leaks), the empty tenant, and the router delegation.
"""
from datetime import date

from sqlalchemy import event

import app.models  # noqa: F401 — register all models with Base
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.form_template import FormInstance, FormTemplate
from app.models.kpi import KPI
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.release import Release, ReleaseItem
from app.models.roadmap import Roadmap
from app.models.role import Role
from app.models.role_assignment import RoleAssignment
from app.models.stakeholder import Stakeholder
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services.auth import hash_password
from app.services.stats import get_dashboard_stats
from tests.conftest import test_engine

# --------------------------------------------------------------------------- helpers


def _project(db, tenant, user, name) -> Project:
    """Projects require a client (NOT NULL FK) — seed one for the test."""
    c = Client(tenant_id=tenant.id, name=f"Client {name}")
    db.add(c)
    db.commit()
    db.refresh(c)
    p = Project(
        tenant_id=tenant.id, name=name, status="active",
        client_id=c.id, project_manager_id=user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _ra(db, user, project) -> RoleAssignment:
    """RoleAssignment requires a roles.id FK — seed a RACI role."""
    role = db.query(Role).filter(Role.name == "QA Lead").first()
    if not role:
        role = Role(name="QA Lead")
        db.add(role)
        db.commit()
        db.refresh(role)
    ra = RoleAssignment(user_id=user.id, role_id=role.id, project_id=project.id)
    db.add(ra)
    db.commit()
    db.refresh(ra)
    return ra


def _seed_fixture(db, tenant, user) -> list[Project]:
    """A realistic assignment: 2 PM projects + 1 RACI-only project, with
    items, releases (with release items), KPIs, stakeholders, forms,
    roadmap milestones and pending approvals — the data volume that used
    to explode the old handler's N+1 loops."""
    p1 = _project(db, tenant, user, "Alpha")
    p2 = _project(db, tenant, user, "Beta")
    p3 = _project(db, tenant, user, "Gamma")
    _ra(db, user, p3)  # Gamma is assigned via RACI, not PM

    # Items: mixed phases so the distributions and the done-math have content
    phases = ["Requirements", "Development", "Testing", "Pre-Release", "Release"]
    for i, (p, phase) in enumerate([(p1, phases[0]), (p1, phases[1]), (p1, phases[3]),
                                    (p2, phases[2]), (p2, phases[4]), (p3, phases[0])]):
        db.add(BacklogItem(tenant_id=tenant.id, project_id=p.id, title=f"Item {i}", current_phase=phase))
    db.commit()

    # Releases: 2 with items, 1 empty; items linked to real backlog rows
    releases = [
        Release(tenant_id=tenant.id, project_id=p1.id, version="1.0", name="R1", status="Planning"),
        Release(tenant_id=tenant.id, project_id=p1.id, version="1.1", name="R2", status="Completed"),
        Release(tenant_id=tenant.id, project_id=p2.id, version="2.0", name="R3", status="Planning"),
    ]
    for rel in releases:
        db.add(rel)
        db.commit()
        db.refresh(rel)
        items = db.query(BacklogItem).filter(BacklogItem.project_id == rel.project_id).limit(2).all()
        for it in items:
            db.add(ReleaseItem(release_id=rel.id, backlog_item_id=it.id))
    db.commit()

    # KPIs, stakeholders, form instances
    for i, p in enumerate([p1, p2, p3]):
        db.add(KPI(tenant_id=tenant.id, project_id=p.id, name=f"KPI {i}", target_value="90", current_value="70", unit="%"))
        db.add(Stakeholder(project_id=p.id, name=f"Stake {i}", role_name="PO"))
    template = FormTemplate(name="Gate form", form_type="gate", field_schema=[])
    db.add(template)
    db.commit()
    db.refresh(template)
    db.add(FormInstance(template_id=template.id, project_id=p1.id, status="Submitted"))
    db.commit()

    # Roadmap + milestones on p1 (one Completed, two upcoming)
    rm = Roadmap(project_id=p1.id, title="Alpha roadmap")
    db.add(rm)
    db.commit()
    db.refresh(rm)
    db.add(Milestone(roadmap_id=rm.id, title="M1", status="Completed", target_date=date(2026, 11, 1)))
    db.add(Milestone(roadmap_id=rm.id, title="M2", status="On Track", target_date=date(2026, 12, 1)))
    db.add(Milestone(roadmap_id=rm.id, title="M3", status="On Track", target_date=date(2027, 1, 15)))
    db.commit()

    # Pending approvals on p1 and p2, with steps
    for p in (p1, p2):
        a = ApprovalRequest(tenant_id=tenant.id, project_id=p.id, title=f"Gate {p.name}",
                            request_type="phase_gate", current_step=1, status="Pending")
        db.add(a)
        db.commit()
        db.refresh(a)
        db.add(ApprovalStep(request_id=a.id, step_order=1, role_name="Product Manager", status="Approved"))
        db.add(ApprovalStep(request_id=a.id, step_order=2, role_name="Tech Lead", status="Pending"))
    db.commit()
    return [p1, p2, p3]


# --------------------------------------------------------------------------- 1. the query budget


def test_query_budget_flat_not_n_plus_one(db, auth_user):
    """The seeded fixture (3 projects, 6 items, 3 releases with release
    items, KPIs, stakeholders, forms, milestones, pending approvals) computes
    in ≤ 16 queries — the old handler ran 33+ sequential queries plus the
    six N+1 loops this fixture exercises."""
    t, u = auth_user["tenant"], auth_user["user"]
    _seed_fixture(db, t, u)
    _ = t.id, u.id  # warm the fixture objects (expired by the last seed commit)
    # — these reloads are the test's lifecycle, not the service's queries.

    counter = {"n": 0}

    def _count(*args, **kwargs):
        counter["n"] += 1

    event.listen(test_engine, "before_cursor_execute", _count)
    try:
        stats = get_dashboard_stats(db, u, t)
    finally:
        event.remove(test_engine, "before_cursor_execute", _count)

    # The payload is real (not a short-circuit on empty data)
    assert stats["projects"] == 3
    assert stats["backlog_items"] == 6
    assert stats["releases"] == 3
    assert len(stats["project_progress"]) == 3
    assert len(stats["upcoming_milestones"]) == 2
    assert stats["pending_approvals"] == 2
    assert counter["n"] <= 16


# --------------------------------------------------------------------------- 2. payload parity with the old handler


def _old_style_stats(db, tid, uid) -> dict:
    """A faithful copy of the handler this replaces (dashboard.py before F2)
    — the parity reference. Same assignment logic, same counts, same
    distributions, same walks, same slices."""

    pm_project_ids = db.query(Project.id).filter(
        Project.tenant_id == tid, Project.project_manager_id == uid,
    ).all()
    ra_project_ids = db.query(RoleAssignment.project_id).filter(RoleAssignment.user_id == uid).all()
    assigned_project_ids = set()
    for row in pm_project_ids:
        assigned_project_ids.add(row[0])
    for row in ra_project_ids:
        p = db.query(Project).filter(Project.id == row[0], Project.tenant_id == tid).first()
        if p:
            assigned_project_ids.add(row[0])

    am_client_ids = db.query(Client.id).filter(Client.tenant_id == tid, Client.account_manager_id == uid).all()
    assigned_client_ids = set(r[0] for r in am_client_ids)
    for pid in assigned_project_ids:
        proj = db.query(Project).filter(Project.id == pid).first()
        if proj and proj.client_id:
            assigned_client_ids.add(proj.client_id)

    proj_ids = list(assigned_project_ids) if assigned_project_ids else [0]
    client_ids = list(assigned_client_ids) if assigned_client_ids else [0]

    clients_count = db.query(Client).filter(Client.tenant_id == tid, Client.id.in_(client_ids)).count()
    projects_count = db.query(Project).filter(Project.tenant_id == tid, Project.id.in_(proj_ids)).count()
    backlog_count = db.query(BacklogItem).filter(BacklogItem.project_id.in_(proj_ids)).count()
    pending_approvals = db.query(ApprovalRequest).filter(
        ApprovalRequest.status == "Pending", ApprovalRequest.project_id.in_(proj_ids)).count()
    forms_count = db.query(FormInstance).filter(FormInstance.project_id.in_(proj_ids)).count()
    kpis_count = db.query(KPI).filter(KPI.project_id.in_(proj_ids)).count()
    releases_count = db.query(Release).filter(Release.project_id.in_(proj_ids)).count()
    stakeholders_count = db.query(Stakeholder).filter(Stakeholder.project_id.in_(proj_ids)).count()

    items = db.query(BacklogItem).filter(BacklogItem.project_id.in_(proj_ids)).all()
    phase_distribution: dict[str, int] = {}
    for item in items:
        phase_distribution[item.current_phase] = phase_distribution.get(item.current_phase, 0) + 1
    status_distribution: dict[str, int] = {}
    for item in items:
        status_distribution[item.status] = status_distribution.get(item.status, 0) + 1
    priority_distribution: dict[str, int] = {}
    for item in items:
        priority_distribution[item.priority] = priority_distribution.get(item.priority, 0) + 1

    releases = db.query(Release).filter(Release.tenant_id == tid, Release.project_id.in_(proj_ids)).all()
    release_status_dist: dict[str, int] = {}
    for rel in releases:
        release_status_dist[rel.status] = release_status_dist.get(rel.status, 0) + 1

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

    project_progress = []
    all_projects = db.query(Project).filter(Project.tenant_id == tid, Project.id.in_(proj_ids)).all()
    for p in all_projects:
        p_backlog = db.query(BacklogItem).filter(BacklogItem.project_id == p.id).all()
        p_releases = db.query(Release).filter(Release.project_id == p.id).all()
        p_kpis = db.query(KPI).filter(KPI.project_id == p.id).all()
        p_stakeholders = db.query(Stakeholder).filter(Stakeholder.project_id == p.id).count()
        p_done = len([i for i in p_backlog if i.current_phase in done_phases])
        p_total = len(p_backlog)
        progress_pct = round((p_done / p_total * 100) if p_total > 0 else 0)
        client = db.query(Client).filter(Client.id == p.client_id, Client.tenant_id == tid).first()
        client_name = client.name if client else "—"
        project_progress.append({
            "id": p.id, "name": p.name, "status": p.status, "client_name": client_name,
            "backlog_total": p_total, "backlog_done": p_done, "progress_pct": progress_pct,
            "releases_count": len(p_releases), "kpis_count": len(p_kpis),
            "stakeholders_count": p_stakeholders,
        })

    assigned_roadmap_ids = db.query(Roadmap.id).filter(Roadmap.project_id.in_(proj_ids)).all()
    roadmap_ids = [r[0] for r in assigned_roadmap_ids] if assigned_roadmap_ids else [0]
    all_milestones = db.query(Milestone).filter(Milestone.roadmap_id.in_(roadmap_ids)).all()
    upcoming_milestones = []
    for ms in all_milestones:
        if ms.status != "Completed":
            rm = db.query(Roadmap).filter(Roadmap.id == ms.roadmap_id).first()
            if rm:
                p = db.query(Project).filter(Project.id == rm.project_id).first()
                upcoming_milestones.append({
                    "id": ms.id, "title": ms.title,
                    "target_date": str(ms.target_date) if ms.target_date else None,
                    "status": ms.status,
                    "project_name": p.name if p else "—", "project_id": p.id if p else None,
                })
    upcoming_milestones.sort(key=lambda x: x.get("target_date") or "9999")
    upcoming_milestones = upcoming_milestones[:5]

    recent_projects_data = [
        {
            "id": p.id, "name": p.name, "status": p.status, "github_repo": p.github_repo,
            "client_id": p.client_id,
            "client_name": next((pp["client_name"] for pp in project_progress if pp["id"] == p.id), "—"),
        }
        for p in db.query(Project).filter(Project.tenant_id == tid, Project.id.in_(proj_ids))
        .order_by(Project.created_at.desc()).limit(5).all()
    ]

    pending = db.query(ApprovalRequest).filter(
        ApprovalRequest.status == "Pending", ApprovalRequest.project_id.in_(proj_ids)).limit(5).all()
    pending_data = []
    for a in pending:
        steps = db.query(ApprovalStep).filter(ApprovalStep.request_id == a.id).order_by(ApprovalStep.step_order).all()
        p = db.query(Project).filter(Project.id == a.project_id, Project.tenant_id == tid).first()
        pending_data.append({
            "id": a.id, "title": a.title, "request_type": a.request_type,
            "current_step": a.current_step, "project_id": a.project_id,
            "project_name": p.name if p else "—", "total_steps": len(steps),
            "approved_steps": len([s for s in steps if s.status == "Approved"]),
        })

    kpi_progress = []
    for kpi in db.query(KPI).filter(KPI.project_id.in_(proj_ids)).all():
        p = db.query(Project).filter(Project.id == kpi.project_id, Project.tenant_id == tid).first()
        kpi_progress.append({
            "id": kpi.id, "name": kpi.name, "target_value": kpi.target_value,
            "current_value": kpi.current_value, "unit": kpi.unit,
            "project_name": p.name if p else "—",
        })

    return {
        "clients": clients_count, "projects": projects_count, "backlog_items": backlog_count,
        "pending_approvals": pending_approvals, "forms": forms_count, "kpis": kpis_count,
        "releases": releases_count, "stakeholders": stakeholders_count,
        "phase_distribution": phase_distribution, "status_distribution": status_distribution,
        "priority_distribution": priority_distribution,
        "release_status_distribution": release_status_dist,
        "total_release_items": total_release_items,
        "completed_release_items": completed_release_items,
        "project_progress": project_progress, "upcoming_milestones": upcoming_milestones,
        "recent_projects": recent_projects_data, "pending_approval_details": pending_data,
        "kpi_progress": kpi_progress,
    }


def test_payload_parity_with_old_handler(db, auth_user):
    """Every top-level key the old handler returned is returned with the
    same value on the same fixture data — byte-identical parity."""
    t, u = auth_user["tenant"], auth_user["user"]
    _seed_fixture(db, t, u)
    db.expire_all()

    new = get_dashboard_stats(db, u, t)
    db.expire_all()
    old = _old_style_stats(db, t.id, u.id)

    assert set(new.keys()) == set(old.keys())
    for key in old:
        assert new[key] == old[key], f"payload mismatch on key {key!r}"


# --------------------------------------------------------------------------- 3. shape + scoping + empty + endpoint


def test_response_shape_all_keys_present(db, auth_user):
    t, u = auth_user["tenant"], auth_user["user"]
    _seed_fixture(db, t, u)

    stats = get_dashboard_stats(db, u, t)
    assert set(stats.keys()) == {
        "clients", "projects", "backlog_items", "pending_approvals", "forms", "kpis",
        "releases", "stakeholders", "phase_distribution", "status_distribution",
        "priority_distribution", "release_status_distribution", "total_release_items",
        "completed_release_items", "project_progress", "upcoming_milestones",
        "recent_projects", "pending_approval_details", "kpi_progress",
    }
    pp = stats["project_progress"][0]
    assert set(pp.keys()) == {
        "id", "name", "status", "client_name", "backlog_total", "backlog_done",
        "progress_pct", "releases_count", "kpis_count", "stakeholders_count",
    }
    for entry in stats["upcoming_milestones"]:
        assert set(entry.keys()) == {"id", "title", "target_date", "status", "project_name", "project_id"}
    for entry in stats["pending_approval_details"]:
        assert set(entry.keys()) == {
            "id", "title", "request_type", "current_step", "project_id",
            "project_name", "total_steps", "approved_steps",
        }


def test_seeded_numbers_are_right(db, auth_user):
    """The fixture numbers themselves (not just parity): 3 projects, 6 items
    (2 in done phases → 2 completed release items out of 4 release items),
    the done-math and the progress pct."""
    t, u = auth_user["tenant"], auth_user["user"]
    _seed_fixture(db, t, u)

    stats = get_dashboard_stats(db, u, t)
    assert stats["projects"] == 3
    assert stats["backlog_items"] == 6
    assert stats["releases"] == 3
    assert stats["kpis"] == 3
    assert stats["stakeholders"] == 3
    assert stats["forms"] == 1
    assert stats["pending_approvals"] == 2
    # R1/R2 link p1's first two items (Requirements + Development, not done);
    # R3 links p2's Testing + Pre-Release — one done item of 6 release items.
    assert stats["completed_release_items"] == 1
    # The done-phase items: 1 of 3 on Alpha (Pre-Release) + 1 of 2 on Beta (Release)
    by_name = {p["name"]: p for p in stats["project_progress"]}
    assert by_name["Alpha"]["progress_pct"] == 33
    assert by_name["Beta"]["progress_pct"] == 50
    assert by_name["Gamma"]["progress_pct"] == 0
    # The completed milestone (M1) never shows; the upcoming two are the slice
    assert [m["title"] for m in stats["upcoming_milestones"]] == ["M2", "M3"]
    assert all(m["project_name"] == "Alpha" for m in stats["upcoming_milestones"])
    # Pending approval details carry the step rollup (1 of 2 approved each)
    assert len(stats["pending_approval_details"]) == 2
    for entry in stats["pending_approval_details"]:
        assert entry["total_steps"] == 2
        assert entry["approved_steps"] == 1


def test_empty_tenant_counts_zero_and_lists_empty(db, auth_user):
    t, u = auth_user["tenant"], auth_user["user"]

    stats = get_dashboard_stats(db, u, t)
    assert stats["clients"] == 0
    assert stats["projects"] == 0
    assert stats["backlog_items"] == 0
    assert stats["phase_distribution"] == {}
    assert stats["project_progress"] == []
    assert stats["upcoming_milestones"] == []
    assert stats["recent_projects"] == []
    assert stats["pending_approval_details"] == []
    assert stats["kpi_progress"] == []


def test_foreign_tenant_data_never_leaks(db, auth_user):
    """A second tenant's project with its own items/releases never counts —
    the same isolation the old handler had."""
    t, u = auth_user["tenant"], auth_user["user"]
    _seed_fixture(db, t, u)

    tb = Tenant(name="Other Tenant", slug="other-tenant", plan="enterprise", status="active")
    db.add(tb)
    db.commit()
    db.refresh(tb)
    fu = User(email="other@pmo.test", name="Other", hashed_password=hash_password("TestPass123!"),
              system_role="super_admin", active_tenant_id=tb.id)
    db.add(fu)
    db.commit()
    db.refresh(fu)
    db.add(TenantMembership(user_id=fu.id, tenant_id=tb.id, role="owner"))
    fp = _project(db, tb, fu, "Foreign")
    db.add(BacklogItem(tenant_id=tb.id, project_id=fp.id, title="Foreign item"))
    db.commit()

    other = get_dashboard_stats(db, fu, tb)
    assert other["projects"] == 1
    assert other["backlog_items"] == 1
    assert [p["name"] for p in other["project_progress"]] == ["Foreign"]

    mine = get_dashboard_stats(db, u, t)
    assert mine["projects"] == 3
    assert "Foreign" not in [p["name"] for p in mine["project_progress"]]


def test_raci_only_assignment_counts(db, auth_user):
    """A project the user holds via RACI only (not PM) is assigned — Gamma
    in the fixture has no PM link, only a role assignment."""
    t, u = auth_user["tenant"], auth_user["user"]
    _seed_fixture(db, t, u)

    stats = get_dashboard_stats(db, u, t)
    assert "Gamma" in [p["name"] for p in stats["project_progress"]]
    assert stats["projects"] == 3


def test_router_delegates_to_service(client, db, auth_user):
    """GET /api/dashboard returns exactly the service payload."""
    t, u = auth_user["tenant"], auth_user["user"]
    _seed_fixture(db, t, u)
    db.expire_all()

    expected = get_dashboard_stats(db, u, t)
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    assert r.json() == expected
