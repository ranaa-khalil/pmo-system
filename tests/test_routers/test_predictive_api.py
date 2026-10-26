"""Tests for the predictive flags API + KpiHistory snapshot wiring (P3).

GET /api/ai/predictive-flags — derived KPI flags (off-target / deteriorating
trend), scoped to assigned projects. PUT /api/kpis/{id} writes a KpiHistory
snapshot row whenever current_value changes — the trend's data source.
"""
import pytest

import app.models  # noqa: F401
from app.models.kpi import KPI
from app.models.kpi_history import KpiHistory
from app.models.project import Project
from app.models.tenant import Tenant


@pytest.fixture()
def pf_world(client, db, auth_user):
    """The shared owner (PM of their project) + a project with a KPI."""
    tenant = auth_user["tenant"]
    user = auth_user["user"]
    project = Project(name="PF P", client_id=1, tenant_id=tenant.id, project_manager_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    kpi = KPI(tenant_id=tenant.id, project_id=project.id, name="Uptime", target_value="99.9", current_value="98.0", unit="%")
    db.add(kpi)
    db.commit()
    db.refresh(kpi)
    return {"tenant": tenant, "user": user, "project": project, "kpi": kpi}


def test_predictive_flags_endpoint(pf_world, client):
    resp = client.get("/api/ai/predictive-flags")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    flag = data["flags"][0]
    assert flag["kpi_name"] == "Uptime"
    assert flag["direction"] == "higher_is_better"
    assert flag["kind"] == "kpi"


def test_predictive_flags_project_scoped(pf_world, client, db):
    """?project_id= scopes to one project; other projects' KPIs never leak."""
    resp = client.get(f"/api/ai/predictive-flags?project_id={pf_world['project'].id}")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert all(f["project_id"] == pf_world["project"].id for f in resp.json()["flags"])


def test_predictive_flags_other_tenant_project_404(pf_world, client, db):
    from app.models.project import Project as P
    other = Tenant(name="Other PF", slug="other-pf", plan="team")
    db.add(other)
    db.commit()
    db.refresh(other)
    hidden = P(name="Hidden PF", client_id=1, tenant_id=other.id)
    db.add(hidden)
    db.commit()
    db.refresh(hidden)

    resp = client.get(f"/api/ai/predictive-flags?project_id={hidden.id}")
    assert resp.status_code == 404


def test_predictive_flags_empty_when_healthy(pf_world, client, db):
    kpi = db.query(KPI).filter(KPI.id == pf_world["kpi"].id).first()
    kpi.current_value = "99.95"
    db.commit()
    resp = client.get("/api/ai/predictive-flags")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_kpi_update_writes_history_snapshot(pf_world, client, db):
    """PUT /api/kpis/{id} with a changed current_value writes a KpiHistory row."""
    kpi = pf_world["kpi"]
    resp = client.put(f"/api/kpis/{kpi.id}", json={"current_value": "99.2"})
    assert resp.status_code == 200

    rows = db.query(KpiHistory).filter(KpiHistory.kpi_id == kpi.id).all()
    assert len(rows) == 1
    assert rows[0].value == "99.2"
    assert rows[0].source == "manual"
    assert rows[0].tenant_id == pf_world["tenant"].id


def test_kpi_update_same_value_no_snapshot(pf_world, client, db):
    """Updating a different field (not current_value) writes no history row."""
    kpi = pf_world["kpi"]
    resp = client.put(f"/api/kpis/{kpi.id}", json={"name": "Uptime (prod)"})
    assert resp.status_code == 200
    assert db.query(KpiHistory).filter(KpiHistory.kpi_id == kpi.id).count() == 0


def test_kpi_history_feeds_trend(pf_world, client, db):
    """Two history rows → the flags endpoint reports a trend with points."""
    kpi = pf_world["kpi"]
    client.put(f"/api/kpis/{kpi.id}", json={"current_value": "99.2"})
    client.put(f"/api/kpis/{kpi.id}", json={"current_value": "98.8"})
    client.put(f"/api/kpis/{kpi.id}", json={"current_value": "98.1"})

    data = client.get("/api/ai/predictive-flags").json()
    flag = data["flags"][0]
    assert flag["trend"] == "deteriorating"  # 99.2 → 98.8 → 98.1, higher-is-better
    assert flag["history_points"] == 3
    assert flag["severity"] == "high"  # off target AND deteriorating
