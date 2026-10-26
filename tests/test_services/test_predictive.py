"""Tests for the predictive flags service (P3).

predictive_flags(db, tenant, project_ids) computes forward-looking warnings
from real data — never invented:
- KPI flags: current_value below target (direction-aware), trend from
  KpiHistory rows (2+ points → deteriorating/improving/stable)
- Cycle-time flags: avg cycle time worsening vs the previous window
- Capacity flags: operations projects — overdue tasks piling up

Template-aware: the flag `kind` carries the project's lifecycle vocabulary
(drift for AI projects, spend/CAC for marketing, capacity for operations).
"""
import pytest

import app.models  # noqa: F401
from app.models.kpi import KPI
from app.models.kpi_history import KpiHistory
from app.models.project import Project
from app.services import predictive


@pytest.fixture()
def flag_world(db, auth_user):
    """A software project with one KPI (no history yet)."""
    tenant = auth_user["tenant"]
    project = Project(name="Flags P", client_id=1, tenant_id=tenant.id, project_type="software")
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "project": project}


def _kpi(db, tenant, project, name="Uptime", target="99.9", current="99.7", unit="%"):
    k = KPI(tenant_id=tenant.id, project_id=project.id, name=name,
            target_value=target, current_value=current, unit=unit)
    db.add(k)
    db.commit()
    db.refresh(k)
    return k


def test_no_flags_when_healthy(flag_world, db):
    k = _kpi(db, flag_world["tenant"], flag_world["project"], current="99.95")
    db.add(KpiHistory(tenant_id=flag_world["tenant"].id, project_id=flag_world["project"].id, kpi_id=k.id, value="99.97"))
    db.commit()
    flags = predictive.predictive_flags(db, flag_world["tenant"], [flag_world["project"].id])
    assert flags == []


def test_kpi_below_target_flag(flag_world, db):
    """Uptime below target (higher-is-better) → a KPI flag with direction."""
    _kpi(db, flag_world["tenant"], flag_world["project"], name="Uptime", target="99.9", current="98.2")
    flags = predictive.predictive_flags(db, flag_world["tenant"], [flag_world["project"].id])
    assert len(flags) == 1
    f = flags[0]
    assert f["entity_type"] == "kpi_flag"
    assert f["kpi_name"] == "Uptime"
    assert f["direction"] == "higher_is_better"
    assert "98.2" in f["message"] and "99.9" in f["message"]
    assert f["project_id"] == flag_world["project"].id


def test_kpi_over_target_flag_when_lower_is_better(flag_world, db):
    """CAC above target (lower-is-better) → flagged."""
    _kpi(db, flag_world["tenant"], flag_world["project"], name="CAC", target="100", current="140", unit="SAR")
    flags = predictive.predictive_flags(db, flag_world["tenant"], [flag_world["project"].id])
    assert len(flags) == 1
    assert flags[0]["kpi_name"] == "CAC"
    assert flags[0]["direction"] == "lower_is_better"


def test_kpi_deteriorating_trend_from_history(flag_world, db):
    """History getting worse → trend=deteriorating even when still on target."""
    k = _kpi(db, flag_world["tenant"], flag_world["project"], name="NPS", target="50", current="45")
    # 60 → 55 → 45: falling (higher-is-better)
    db.add(KpiHistory(tenant_id=flag_world["tenant"].id, project_id=flag_world["project"].id, kpi_id=k.id, value="60"))
    db.add(KpiHistory(tenant_id=flag_world["tenant"].id, project_id=flag_world["project"].id, kpi_id=k.id, value="55"))
    db.add(KpiHistory(tenant_id=flag_world["tenant"].id, project_id=flag_world["project"].id, kpi_id=k.id, value="45"))
    db.commit()
    flags = predictive.predictive_flags(db, flag_world["tenant"], [flag_world["project"].id])
    assert len(flags) == 1
    assert flags[0]["trend"] == "deteriorating"
    assert flags[0]["history_points"] == 3


def test_kpi_improving_trend_not_flagged(flag_world, db):
    """History getting better → no trend flag when on target."""
    k = _kpi(db, flag_world["tenant"], flag_world["project"], name="NPS", target="50", current="55")
    db.add(KpiHistory(tenant_id=flag_world["tenant"].id, project_id=flag_world["project"].id, kpi_id=k.id, value="40"))
    db.add(KpiHistory(tenant_id=flag_world["tenant"].id, project_id=flag_world["project"].id, kpi_id=k.id, value="48"))
    db.add(KpiHistory(tenant_id=flag_world["tenant"].id, project_id=flag_world["project"].id, kpi_id=k.id, value="55"))
    db.commit()
    flags = predictive.predictive_flags(db, flag_world["tenant"], [flag_world["project"].id])
    assert flags == []


def test_non_numeric_kpi_ignored(flag_world, db):
    """A KPI with non-numeric values never crashes or flags."""
    _kpi(db, flag_world["tenant"], flag_world["project"], name="Mood", target="high", current="ok")
    flags = predictive.predictive_flags(db, flag_world["tenant"], [flag_world["project"].id])
    assert flags == []


def test_template_aware_kind(flag_world, db, auth_user):
    """AI projects get drift vocabulary; marketing gets spend vocabulary."""
    ai_project = Project(name="AI Flags", client_id=1, tenant_id=flag_world["tenant"].id, project_type="ai")
    mkt_project = Project(name="Mkt Flags", client_id=1, tenant_id=flag_world["tenant"].id, project_type="marketing")
    db.add_all([ai_project, mkt_project])
    db.commit()
    db.refresh(ai_project)
    db.refresh(mkt_project)

    _kpi(db, flag_world["tenant"], ai_project, name="Model accuracy", target="95", current="88")
    _kpi(db, flag_world["tenant"], mkt_project, name="CTR", target="3", current="1.2")

    flags = predictive.predictive_flags(db, flag_world["tenant"],
                                        [ai_project.id, mkt_project.id])
    kinds = {f["project_id"]: f["kind"] for f in flags}
    assert kinds[ai_project.id] == "drift"
    assert kinds[mkt_project.id] == "spend"


def test_flags_scoped_to_projects(flag_world, db, auth_user):
    """Another project's KPIs never leak into the flags list."""
    other = Project(name="Other Flags", client_id=1, tenant_id=flag_world["tenant"].id)
    db.add(other)
    db.commit()
    db.refresh(other)
    _kpi(db, flag_world["tenant"], other, name="Hidden KPI", target="10", current="1")

    flags = predictive.predictive_flags(db, flag_world["tenant"], [flag_world["project"].id])
    assert all(f["project_id"] == flag_world["project"].id for f in flags)
    assert not any(f["kpi_name"] == "Hidden KPI" for f in flags)
