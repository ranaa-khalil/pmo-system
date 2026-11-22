"""Tests for the project-health composite service (R3) — computed health with visible inputs.

compute_project_health is the single builder behind GET /api/projects/{id}/health:
the router's original sub-score math (schedule = done/total, approvals -15/gate,
tasks -20/overdue, kpis on-target ratio) plus gate aging — the oldest pending
gate past a 3-day grace costs 1 approval_score point/day, capped at 15 — and a
`why` chip list per sub-score built from real rows. Response keys are
additive-only: everything the router returned before R3 keeps its meaning.
"""
from datetime import date, timedelta

import pytest

import app.models  # noqa: F401 — register all models with Base
from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
from app.models.project import Project
from app.models.release import Release, ReleaseItem
from app.models.tenant import Tenant
from app.models.user_task import UserTask
from app.services.health import compute_project_health

# Every key the router returned before R3 — the overview card + existing tests
# consume these; the service must keep them byte-identical in meaning.
LEGACY_KEYS = [
    "health_score", "status", "status_color", "schedule_score", "approval_score",
    "task_score", "kpi_score", "total_items", "completed_items",
    "phase_distribution", "active_releases", "pending_approvals",
    "overdue_tasks", "kpis_below_target", "kpi_progress",
]


def _stamp(days_ago: int) -> str:
    """A created_at string exactly days_ago old regardless of run time (local noon)."""
    return (date.today() - timedelta(days=days_ago)).strftime("%Y-%m-%d") + " 12:00:00"


@pytest.fixture()
def health_world(db, auth_user):
    """The shared tenant + one empty project."""
    project = Project(name="Health World", client_id=1, tenant_id=auth_user["tenant"].id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": auth_user["tenant"], "user": auth_user["user"], "project": project}


def _add_item(db, project, tenant, phase="Requirements", target_release=None):
    item = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title=f"Item {phase}",
        current_phase=phase, target_release=target_release,
    )
    db.add(item)
    db.flush()  # assign the PK before callers read .id
    return item


def _add_pending_approval(db, project, tenant, title="Gate", days_ago=None):
    approval = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id, title=title,
        request_type="release", status="Pending",
        created_at=_stamp(days_ago) if days_ago is not None else None,
    )
    db.add(approval)
    return approval


def _add_kpi(db, project, tenant, name, target, current):
    kpi = KPI(tenant_id=tenant.id, project_id=project.id, name=name,
              target_value=target, current_value=current, unit="%")
    db.add(kpi)
    return kpi


def test_healthy_project_scores_100(health_world, db):
    project, tenant = health_world["project"], health_world["tenant"]
    for _ in range(4):
        _add_item(db, project, tenant, phase="Ready for UAT")
    _add_kpi(db, project, tenant, "NPS", "100", "100")
    db.commit()

    data = compute_project_health(db, tenant.id, project.id)
    assert data["health_score"] == 100
    assert data["status"] == "Healthy"
    assert data["status_color"] == "emerald"
    assert data["approval_score"] == 100


def test_pending_approvals_reduce_approval_score_by_count(health_world, db):
    project, tenant = health_world["project"], health_world["tenant"]
    _add_pending_approval(db, project, tenant, title="Gate 1")
    _add_pending_approval(db, project, tenant, title="Gate 2")
    db.commit()

    data = compute_project_health(db, tenant.id, project.id)
    assert data["pending_approvals"] == 2
    assert data["approval_score"] == 70  # 100 - 2*15, both fresh (within grace)
    assert data["gate_aging"] <= 1
    assert data["why"]["approvals"][0].startswith("2 gates pending · oldest")
    assert not any(c.startswith("aging") for c in data["why"]["approvals"])


def test_gate_aging_older_gate_penalises_more_than_fresh(health_world, db):
    tenant = health_world["tenant"]
    fresh_project = health_world["project"]
    aged_project = Project(name="Aged Project", client_id=1, tenant_id=tenant.id)
    db.add(aged_project)
    db.commit()
    db.refresh(aged_project)
    _add_pending_approval(db, fresh_project, tenant, title="Fresh gate")
    _add_pending_approval(db, aged_project, tenant, title="Stale gate", days_ago=30)
    db.commit()

    fresh = compute_project_health(db, tenant.id, fresh_project.id)
    aged = compute_project_health(db, tenant.id, aged_project.id)
    assert aged["gate_aging"] == 30
    assert aged["approval_score"] == 70  # 100 - 15 count - 15 aging (30d, cap)
    assert fresh["approval_score"] == 85  # count rule only
    assert aged["approval_score"] < fresh["approval_score"]


def test_gate_aging_cap(health_world, db):
    project, tenant = health_world["project"], health_world["tenant"]
    _add_pending_approval(db, project, tenant, title="Ancient gate", days_ago=200)
    db.commit()

    data = compute_project_health(db, tenant.id, project.id)
    assert data["gate_aging"] == 200
    assert data["approval_score"] == 70  # aging deduction capped at 15
    assert data["why"]["approvals"] == ["1 gate pending · oldest 200d", "aging -15 pts"]


def test_gate_aging_grace_period_no_penalty_within_three_days(health_world, db):
    project, tenant = health_world["project"], health_world["tenant"]
    _add_pending_approval(db, project, tenant, title="Recent gate", days_ago=2)
    db.commit()

    data = compute_project_health(db, tenant.id, project.id)
    assert data["gate_aging"] == 2
    assert data["approval_score"] == 85  # inside the 3-day grace: count rule only
    assert data["why"]["approvals"] == ["1 gate pending · oldest 2d"]


def test_why_inputs_are_real(health_world, db):
    project, tenant = health_world["project"], health_world["tenant"]
    for _ in range(3):
        _add_item(db, project, tenant, phase="Development")
    _add_pending_approval(db, project, tenant, title="Gate A", days_ago=6)
    _add_pending_approval(db, project, tenant, title="Gate B")
    _add_kpi(db, project, tenant, "Adoption", "100", "50")   # below target
    _add_kpi(db, project, tenant, "Churn", "100", "80")      # below target
    _add_kpi(db, project, tenant, "Coverage", "100", "100")  # on target
    _add_kpi(db, project, tenant, "Uptime", "99", "99")      # on target
    _add_kpi(db, project, tenant, "CSAT", "90", "90")        # on target
    db.add(UserTask(
        tenant_id=tenant.id, project_id=project.id, title="Overdue",
        assigned_to=health_world["user"].id,
        due_date=date.today() - timedelta(days=3), status="In Progress",
    ))
    db.commit()

    data = compute_project_health(db, tenant.id, project.id)
    assert data["why"]["schedule"] == ["0 of 3 items done"]
    assert data["why"]["approvals"] == ["2 gates pending · oldest 6d", "aging -3 pts"]
    assert data["why"]["tasks"] == ["1 overdue"]
    assert data["why"]["kpis"] == ["2 of 5 below target"]
    assert data["kpis_below_target"] == 2
    assert data["approval_score"] == 67  # 100 - 2*15 - min(15, 6-3)


def test_tenant_scoping_other_tenant_rows_do_not_count(health_world, db):
    project, tenant = health_world["project"], health_world["tenant"]
    other_tenant = Tenant(name="Other Tenant", slug="other-tenant", plan="team", status="active")
    db.add(other_tenant)
    db.commit()
    db.refresh(other_tenant)
    # Another tenant's rows on the same project must never move this tenant's score
    db.add(ApprovalRequest(tenant_id=other_tenant.id, project_id=project.id,
                           title="Foreign gate", request_type="release",
                           status="Pending", created_at=_stamp(30)))
    _add_kpi(db, project, other_tenant, "Foreign KPI", "100", "10")
    db.add(UserTask(tenant_id=other_tenant.id, project_id=project.id, title="Foreign task",
                    assigned_to=health_world["user"].id,
                    due_date=date.today() - timedelta(days=5), status="In Progress"))
    db.commit()

    data = compute_project_health(db, tenant.id, project.id)
    assert data["pending_approvals"] == 0
    assert data["overdue_tasks"] == 0
    assert data["kpis_below_target"] == 0
    assert data["gate_aging"] == 0
    assert data["approval_score"] == 100
    assert data["health_score"] == 100
    assert data["status"] == "Healthy"


def test_empty_project_neutral_why_and_full_score(health_world, db):
    project, tenant = health_world["project"], health_world["tenant"]
    data = compute_project_health(db, tenant.id, project.id)
    assert data["health_score"] == 100
    assert data["status"] == "Healthy"
    assert data["total_items"] == 0
    assert data["gate_aging"] == 0
    assert data["why"] == {
        "schedule": ["no items yet"],
        "approvals": ["no pending gates"],
        "tasks": ["no overdue tasks"],
        "kpis": ["no kpis tracked"],
    }


def test_response_key_parity_additive_only(health_world, db):
    project, tenant = health_world["project"], health_world["tenant"]
    _add_item(db, project, tenant, phase="Ready for UAT")
    _add_kpi(db, project, tenant, "NPS", "50", "40")
    _add_pending_approval(db, project, tenant, title="Gate")
    db.commit()

    data = compute_project_health(db, tenant.id, project.id)
    for key in LEGACY_KEYS:
        assert key in data, f"legacy key lost: {key}"
    assert "gate_aging" in data
    assert "why" in data
    assert set(data["why"].keys()) == {"schedule", "approvals", "tasks", "kpis"}


def test_router_endpoint_delegates_with_parity(health_world, client, db):
    project, tenant = health_world["project"], health_world["tenant"]
    _add_item(db, project, tenant, phase="Ready for UAT")
    _add_pending_approval(db, project, tenant, title="Gate", days_ago=10)
    db.commit()

    resp = client.get(f"/api/projects/{project.id}/health")
    assert resp.status_code == 200
    data = resp.json()
    for key in LEGACY_KEYS:
        assert key in data, f"legacy key lost: {key}"
    assert data["gate_aging"] == 10
    assert data["approval_score"] == 78  # 100 - 15 count - min(15, 10-3) aging
    assert data["health_score"] == compute_project_health(db, tenant.id, project.id)["health_score"]


def test_completed_items_formula_and_phase_distribution(health_world, db):
    project, tenant = health_world["project"], health_world["tenant"]
    _add_item(db, project, tenant, phase="Ready for UAT")
    _add_item(db, project, tenant, phase="Ready for UAT")
    _add_item(db, project, tenant, phase="In Progress", target_release="2026-12")
    _add_item(db, project, tenant, phase="In Progress")
    db.commit()

    data = compute_project_health(db, tenant.id, project.id)
    assert data["total_items"] == 4
    # Original formula kept as-is: "Ready for UAT" OR any target_release counts
    # as completed (the target_release item completes even in In Progress).
    assert data["completed_items"] == 3
    assert data["schedule_score"] == 75  # 3/4, min(100, ...)
    assert data["phase_distribution"] == {"Ready for UAT": 2, "In Progress": 2}


def test_active_releases_payload(health_world, db):
    project, tenant = health_world["project"], health_world["tenant"]
    active = Release(tenant_id=tenant.id, project_id=project.id,
                     version="1.2.0", name="Q4 Drop", status="In Progress")
    retired = Release(tenant_id=tenant.id, project_id=project.id,
                      version="1.1.0", name="Old Drop", status="Post-Release")
    db.add_all([active, retired])
    db.commit()
    db.refresh(active)
    db.refresh(retired)
    item_ids = []
    for _ in range(3):
        item_ids.append(_add_item(db, project, tenant).id)
    db.commit()
    for release, count in ((active, 2), (retired, 1)):
        for item_id in item_ids[:count]:
            db.add(ReleaseItem(tenant_id=tenant.id, release_id=release.id, backlog_item_id=item_id))
    db.commit()

    data = compute_project_health(db, tenant.id, project.id)
    assert len(data["active_releases"]) == 1  # Post-Release excluded
    entry = data["active_releases"][0]
    assert entry["version"] == "1.2.0"
    assert entry["name"] == "Q4 Drop"
    assert entry["status"] == "In Progress"
    assert entry["item_count"] == 2
    assert entry["progress"] == 40  # min(100, 2*20)
