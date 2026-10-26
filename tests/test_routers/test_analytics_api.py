"""Tests for the analytics API — project metrics scoped to a tenant.

GET /api/projects/{id}/analytics returns the full summary (velocity,
cycle_time, phase_distribution, cumulative_flow, kpi_trend); the sub-endpoints
return each metric individually. All project lookups are tenant-filtered, so
another tenant's project 404s.
"""
import pytest

import app.models  # noqa: F401
from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
from app.models.project import Project
from app.models.release import Release, ReleaseItem


@pytest.fixture()
def analytics_world(client, db, auth_user):
    """A project with items in several phases, a KPI, and a release with items."""
    tenant = auth_user["tenant"]
    project = Project(name="Analytics P", client_id=1, tenant_id=tenant.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    db.add(BacklogItem(tenant_id=tenant.id, project_id=project.id, title="A", current_phase="Requirements", status="Draft"))
    db.add(BacklogItem(tenant_id=tenant.id, project_id=project.id, title="B", current_phase="Development", status="In Progress"))
    done = BacklogItem(tenant_id=tenant.id, project_id=project.id, title="C", current_phase="Ready for UAT", status="Done")
    db.add(done)
    db.commit()
    db.refresh(done)

    db.add(KPI(tenant_id=tenant.id, project_id=project.id, name="Uptime", target_value="99.9", current_value="99.7", unit="%"))
    db.commit()

    release = Release(tenant_id=tenant.id, project_id=project.id, version="1.0.0", name="R1", status="In Progress")
    db.add(release)
    db.commit()
    db.refresh(release)
    db.add(ReleaseItem(tenant_id=tenant.id, release_id=release.id, backlog_item_id=done.id))
    db.commit()
    return {"tenant": tenant, "project": project, "release": release}


def test_project_analytics_summary(analytics_world, client):
    project = analytics_world["project"]
    resp = client.get(f"/api/projects/{project.id}/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"velocity", "cycle_time", "phase_distribution", "cumulative_flow", "kpi_trend"}
    assert data["phase_distribution"]["total"] == 3
    assert data["phase_distribution"]["phases"]["Development"] == 1
    assert len(data["kpi_trend"]) == 1


def test_velocity_endpoint(analytics_world, client):
    project = analytics_world["project"]
    resp = client.get(f"/api/projects/{project.id}/analytics/velocity")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["version"] == "1.0.0"
    assert rows[0]["total_items"] == 1


def test_burndown_endpoint_empty_release_ok(analytics_world, client):
    release = analytics_world["release"]
    resp = client.get(f"/api/releases/{release.id}/analytics/burndown")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1  # timeline from creation to today


def test_cycle_time_endpoint(analytics_world, client):
    project = analytics_world["project"]
    resp = client.get(f"/api/projects/{project.id}/analytics/cycle-time")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"avg_cycle_time_days", "items_measured", "min_days", "max_days"}
    assert data["items_measured"] >= 1  # the Ready-for-UAT item


def test_cumulative_flow_endpoint(analytics_world, client):
    project = analytics_world["project"]
    resp = client.get(f"/api/projects/{project.id}/analytics/cumulative-flow")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["total"] == 3


def test_phase_distribution_endpoint(analytics_world, client):
    project = analytics_world["project"]
    resp = client.get(f"/api/projects/{project.id}/analytics/phase-distribution")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phases"] == {"Requirements": 1, "Development": 1, "Ready for UAT": 1}


def test_kpi_trend_endpoint(analytics_world, client):
    project = analytics_world["project"]
    resp = client.get(f"/api/projects/{project.id}/analytics/kpi-trend")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Uptime"


def test_analytics_other_tenant_project_404(analytics_world, client, db, auth_user):
    """Another tenant's project is invisible — 404, not data."""
    from app.models.tenant import Tenant

    other = Tenant(name="Other Co", slug="other-co", plan="team")
    db.add(other)
    db.commit()
    db.refresh(other)
    other_project = Project(name="Hidden", client_id=1, tenant_id=other.id)
    db.add(other_project)
    db.commit()
    db.refresh(other_project)

    resp = client.get(f"/api/projects/{other_project.id}/analytics")
    assert resp.status_code == 404
