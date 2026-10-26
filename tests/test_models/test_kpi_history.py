"""Tests for the KpiHistory model — KPI snapshots over time.

KpiHistory rows are written whenever a KPI's current_value changes (KPI
update, copilot advance), giving the trend line the predictive flags read.
Rows are tenant+project scoped like the KPI itself.
"""
import pytest

import app.models  # noqa: F401
from app.models.kpi import KPI
from app.models.kpi_history import KpiHistory
from app.models.project import Project


@pytest.fixture()
def kpi_world(db, auth_user):
    """A project with one KPI."""
    tenant = auth_user["tenant"]
    project = Project(name="KPI Hist P", client_id=1, tenant_id=tenant.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    kpi = KPI(
        tenant_id=tenant.id, project_id=project.id,
        name="Uptime", target_value="99.9", current_value="99.7", unit="%",
    )
    db.add(kpi)
    db.commit()
    db.refresh(kpi)
    return {"tenant": tenant, "project": project, "kpi": kpi}


def test_create_kpi_history_row(kpi_world, db):
    row = KpiHistory(
        tenant_id=kpi_world["tenant"].id,
        project_id=kpi_world["project"].id,
        kpi_id=kpi_world["kpi"].id,
        value="99.7",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    assert row.id is not None
    assert row.value == "99.7"
    assert row.recorded_at is not None


def test_history_scoped_to_kpi(kpi_world, db):
    db.add(KpiHistory(tenant_id=kpi_world["tenant"].id, project_id=kpi_world["project"].id, kpi_id=kpi_world["kpi"].id, value="99.7"))
    db.add(KpiHistory(tenant_id=kpi_world["tenant"].id, project_id=kpi_world["project"].id, kpi_id=kpi_world["kpi"].id, value="99.8"))
    db.commit()
    rows = db.query(KpiHistory).filter(KpiHistory.kpi_id == kpi_world["kpi"].id).order_by(KpiHistory.id).all()
    assert len(rows) == 2
    assert [r.value for r in rows] == ["99.7", "99.8"]
