"""Tests for velocity/sprint planning — a Business-plan gated feature.

compute_velocity(db, project, sprints) derives velocity from completed
backlog items per sprint window (phase Committed = done). recommend_scope
projects how many items fit the next sprint. Endpoints are gated behind
`sprint_planning` (Business plan+) — Free/Team get 403 with an upgrade
message.
"""
from datetime import date, timedelta

import pytest

import app.models  # noqa: F401
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.services.velocity import compute_velocity, recommend_scope


@pytest.fixture()
def vel_world(db):
    tenant = Tenant(name="Vel Co", slug="vel-co", plan="business")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-vel@copilot.test", name="PM", hashed_password="x")
    db.add(pm)
    db.commit()
    db.refresh(pm)
    project = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    # Two recent 2-week sprints of completed items (4 and 6 items)
    now = date.today()
    for i in range(4):
        db.add(BacklogItem(
            tenant_id=tenant.id, project_id=project.id, title=f"S1 item {i}",
            epic="Auth", current_phase="Committed", status="Done",
            updated_at=now - timedelta(days=20),
        ))
    for i in range(6):
        db.add(BacklogItem(
            tenant_id=tenant.id, project_id=project.id, title=f"S2 item {i}",
            epic="Auth", current_phase="Committed", status="Done",
            updated_at=now - timedelta(days=6),
        ))
    # One open item (not counted in velocity)
    db.add(BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Open item",
        epic="Auth", current_phase="Development", status="In Progress",
    ))
    db.commit()
    return {"tenant": tenant, "pm": pm, "project": project}


def test_compute_velocity_counts_done_items_per_sprint(db, vel_world):
    velocity = compute_velocity(db, vel_world["project"], sprint_days=14)
    assert len(velocity["sprints"]) >= 2
    assert velocity["average"] == 5.0  # (4 + 6) / 2


def test_recommend_scope_caps_at_average(db, vel_world):
    rec = recommend_scope(db, vel_world["project"], sprint_days=14)
    assert rec["recommended_items"] == 5  # average velocity
    assert rec["basis"] == "average of completed items per sprint"


def test_velocity_gate_blocks_free_plan(db, vel_world):
    from app.services.plan_enforcement import has_feature
    assert has_feature("free", "sprint_planning") is False
    assert has_feature("business", "sprint_planning") is True
    assert has_feature("enterprise", "sprint_planning") is True
