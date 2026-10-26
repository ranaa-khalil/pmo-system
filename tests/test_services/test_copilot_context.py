"""Tests for the copilot context service — grounded state assembly.

build_context collects what the AI can see, filtered exactly like the dashboard
(user's assigned clients/projects). Every entry carries a source tag
(entity_type + entity_id + title) so answers are grounded and traceable.
"""
from datetime import date, timedelta

import pytest

import app.models  # noqa: F401
from app.models.activity_log import ActivityLog
from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release
from app.models.user import User
from app.models.user_task import UserTask
from app.services.copilot import build_context


@pytest.fixture()
def world(db):
    """A tenant, a PM, two assigned projects, and signal data."""
    from app.models.tenant import Tenant

    tenant = Tenant(name="Copilot Test Co", slug="copilot-test-co")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    pm = User(email="pm@copilot.test", name="PM", hashed_password="x")
    dev = User(email="dev@copilot.test", name="Dev", hashed_password="x")
    db.add_all([pm, dev])
    db.commit()
    db.refresh(pm)

    p1 = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    p2 = Project(name="CloudGate", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add_all([p1, p2])
    db.commit()
    db.refresh(p1)
    db.refresh(p2)

    # Overdue task for the PM
    db.add(UserTask(
        tenant_id=tenant.id, title="Prep UAT checklist", assigned_to=pm.id,
        project_id=p1.id, due_date=date.today() - timedelta(days=3), status="Pending",
    ))
    # Aging item (advanced long ago, still in Development)
    old = (date.today() - timedelta(days=10))
    item = BacklogItem(
        tenant_id=tenant.id, project_id=p1.id, title="SSO login", epic="Auth",
        current_phase="Development", status="In Progress",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    db.add(ActivityLog(
        tenant_id=tenant.id, user_id=pm.id, project_id=p1.id,
        entity_type="backlog_item", entity_id=item.id, action="advanced",
        summary="SSO login advanced to Development", created_at=old,
    ))
    # Pending approval in p1
    db.add(ApprovalRequest(
        tenant_id=tenant.id, project_id=p1.id, title="Release v1.1.0 planning sign-off",
        request_type="release", status="Pending",
    ))
    # A release
    db.add(Release(tenant_id=tenant.id, project_id=p1.id, version="1.1.0", name="Auth release"))
    # An item in p2 (not the PM's focus but assigned project)
    db.add(BacklogItem(
        tenant_id=tenant.id, project_id=p2.id, title="Billing page", epic="Billing",
        current_phase="Requirements", status="Draft",
    ))
    db.commit()
    return {"tenant": tenant, "pm": pm, "dev": dev, "p1": p1, "p2": p2, "item": item}


def test_context_includes_assigned_projects(db, world):
    ctx = build_context(db, world["pm"], world["tenant"])
    names = [p["title"] for p in ctx["projects"]]
    assert "PNU Cloud" in names
    assert "CloudGate" in names


def test_context_includes_overdue_tasks(db, world):
    ctx = build_context(db, world["pm"], world["tenant"])
    overdue = ctx["overdue_tasks"]
    assert len(overdue) == 1
    assert overdue[0]["title"] == "Prep UAT checklist"
    assert overdue[0]["entity_type"] == "user_task"


def test_context_includes_aging_items(db, world):
    ctx = build_context(db, world["pm"], world["tenant"])
    aging = ctx["aging_items"]
    assert len(aging) == 1
    assert aging[0]["title"] == "SSO login"
    assert aging[0]["entity_type"] == "backlog_item"
    assert aging[0]["days_in_phase"] >= 7


def test_context_includes_pending_approvals(db, world):
    ctx = build_context(db, world["pm"], world["tenant"])
    approvals = ctx["pending_approvals"]
    assert len(approvals) == 1
    assert "v1.1.0" in approvals[0]["title"]
    assert approvals[0]["entity_type"] == "approval_request"


def test_context_excludes_other_users_data(db, world):
    """The dev (no assignments) sees nothing — filtered like the dashboard."""
    ctx = build_context(db, world["dev"], world["tenant"])
    assert ctx["projects"] == []
    assert ctx["overdue_tasks"] == []
    assert ctx["pending_approvals"] == []


def test_context_scoped_to_project(db, world):
    """project_id narrows everything to one project."""
    ctx = build_context(db, world["pm"], world["tenant"], project_id=world["p1"].id)
    assert all(p["entity_id"] == world["p1"].id for p in ctx["projects"])
    assert ctx["epic_tree"]["Auth"]["features"][0]["title"] == "SSO login"


def test_every_entry_has_a_source(db, world):
    """Grounding rule: every context entry carries entity_type + entity_id."""
    ctx = build_context(db, world["pm"], world["tenant"])
    for key in ("projects", "overdue_tasks", "aging_items", "pending_approvals"):
        for entry in ctx[key]:
            assert "entity_type" in entry and "entity_id" in entry and "title" in entry
