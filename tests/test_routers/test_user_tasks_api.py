"""Tests for the user tasks API — personal to-dos, summary, scoping.

Tasks are per-user within a tenant: the list shows the current user's tasks
(others' tasks are invisible), and updates/removals are scoped to the owner.
Summary aggregates counts by status.
"""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_task import UserTask
from app.services.auth import create_access_token


@pytest.fixture()
def task_world(client, db, auth_user):
    """The shared user with 2 tasks + another user's task in the same tenant."""
    tenant = auth_user["tenant"]
    user = auth_user["user"]
    db.add(UserTask(tenant_id=tenant.id, title="My open task", assigned_to=user.id, status="In Progress"))
    db.add(UserTask(tenant_id=tenant.id, title="My done task", assigned_to=user.id, status="Completed"))
    other_user = User(email="other@tasks.example.com", name="Other", hashed_password="x", system_role="member", active_tenant_id=tenant.id)
    db.add(other_user)
    db.commit()
    db.refresh(other_user)
    db.add(UserTask(tenant_id=tenant.id, title="Not mine", assigned_to=other_user.id, status="Pending"))
    db.commit()
    return {"tenant": tenant, "user": user, "other_user": other_user}


def test_list_tasks_scoped_to_me(task_world, client):
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()]
    assert "My open task" in titles and "My done task" in titles
    assert "Not mine" not in titles


def test_create_task_defaults_to_me(task_world, client, db):
    resp = client.post("/api/tasks", json={"title": "Brand new", "priority": "High"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["assigned_to"] == task_world["user"].id
    assert data["priority"] == "High"


def test_update_own_task(task_world, client):
    resp = client.put("/api/tasks/1", json={"status": "Completed"})
    # ID 1 belongs to the shared user (fixture order) — but be safe: update by list lookup
    tasks = client.get("/api/tasks").json()
    mine = next(t for t in tasks if t["title"] == "Brand new" or t["title"] == "My open task")
    resp = client.put(f"/api/tasks/{mine['id']}", json={"status": "Completed"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "Completed"


def test_super_admin_can_update_others_task(task_world, client, db):
    """The shared auth user is super_admin — allowed to update any tenant task."""
    other_task = db.query(UserTask).filter(UserTask.title == "Not mine").first()
    resp = client.put(f"/api/tasks/{other_task.id}", json={"status": "Completed"})
    assert resp.status_code == 200
    db.refresh(other_task)
    assert other_task.status == "Completed"


def test_delete_own_task(task_world, client, db):
    task = db.query(UserTask).filter(UserTask.title == "My done task").first()
    resp = client.delete(f"/api/tasks/{task.id}")
    assert resp.status_code == 200
    assert db.query(UserTask).filter(UserTask.id == task.id).first() is None


def test_task_summary(task_world, client):
    resp = client.get("/api/tasks/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2  # only my tasks
    assert data["in_progress"] == 1
    assert data["completed"] == 1
    assert data["active"] == 1  # pending(0) + in_progress(1)


def test_task_with_project_link(task_world, client, db):
    project = Project(name="Task P", client_id=1, tenant_id=task_world["tenant"].id)
    db.add(project)
    db.commit()
    db.refresh(project)
    resp = client.post("/api/tasks", json={"title": "Linked", "project_id": project.id})
    assert resp.status_code == 200
    assert resp.json()["project_id"] == project.id


def test_other_tenant_user_sees_nothing(task_world, client, db):
    """A user from another tenant sees no tasks at all."""
    other_tenant = Tenant(name="Other Task Co", slug="other-task-co", plan="team")
    db.add(other_tenant)
    db.commit()
    db.refresh(other_tenant)
    stranger = User(email="stranger@tasks.example.com", name="S", hashed_password="x", system_role="member", active_tenant_id=other_tenant.id)
    db.add(stranger)
    db.commit()
    db.refresh(stranger)
    from app.models.tenant import TenantMembership
    db.add(TenantMembership(user_id=stranger.id, tenant_id=other_tenant.id, role="member"))
    db.commit()

    token = create_access_token({"sub": str(stranger.id)})
    resp = client.get("/api/tasks", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []
