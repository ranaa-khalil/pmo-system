"""Tests for multi-assignee tasks (Wrike parity: assignee chips + add/remove)."""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User


@pytest.fixture()
def assignee_world(client, db):
    tenant = Tenant(name="Assignee Co", slug="assignee-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-assignee@copilot.test", name="PM", hashed_password="x",
              system_role="project_manager")
    a1 = User(email="a1-assignee@copilot.test", name="Alice One", hashed_password="x")
    a2 = User(email="a2-assignee@copilot.test", name="Bob Two", hashed_password="x")
    db.add_all([pm, a1, a2])
    db.commit()
    db.refresh(pm)
    db.refresh(a1)
    db.refresh(a2)
    for u, role in [(pm, "owner"), (a1, "member"), (a2, "member")]:
        db.add(TenantMembership(user_id=u.id, tenant_id=tenant.id, role=role))
        u.active_tenant_id = tenant.id
    db.commit()
    project = Project(name="Assignee Proj", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "pm": pm, "a1": a1, "a2": a2, "project": project}


def _as(client, user):
    from app.services.auth import create_access_token
    client.headers.update({"Authorization": f"Bearer {create_access_token(data={'sub': str(user.id)})}"})


def test_create_with_assignees(assignee_world, client):
    pm, a1, a2, project = assignee_world["pm"], assignee_world["a1"], assignee_world["a2"], assignee_world["project"]
    _as(client, pm)
    resp = client.post("/api/tasks", json={
        "title": "Shared", "project_id": project.id, "assigned_to": pm.id,
        "assignee_ids": [a1.id, a2.id],
    })
    assert resp.status_code == 200
    data = resp.json()
    ids = {a["id"] for a in data.get("assignees", [])}
    assert a1.id in ids and a2.id in ids


def test_list_includes_assignees(assignee_world, client):
    pm, a1, project = assignee_world["pm"], assignee_world["a1"], assignee_world["project"]
    _as(client, pm)
    client.post("/api/tasks", json={
        "title": "With A1", "project_id": project.id, "assigned_to": pm.id, "assignee_ids": [a1.id],
    })
    rows = client.get("/api/tasks").json()
    task = next(t for t in rows if t["title"] == "With A1")
    assert any(a["id"] == a1.id for a in task.get("assignees", []))


def test_update_replaces_assignees(assignee_world, client):
    pm, a1, a2, project = assignee_world["pm"], assignee_world["a1"], assignee_world["a2"], assignee_world["project"]
    _as(client, pm)
    task = client.post("/api/tasks", json={
        "title": "Replace", "project_id": project.id, "assigned_to": pm.id, "assignee_ids": [a1.id],
    }).json()
    resp = client.put(f"/api/tasks/{task['id']}", json={"assignee_ids": [a2.id]})
    assert resp.status_code == 200
    ids = {a["id"] for a in resp.json().get("assignees", [])}
    assert a2.id in ids and a1.id not in ids


def test_empty_list_clears_assignees(assignee_world, client):
    pm, a1, project = assignee_world["pm"], assignee_world["a1"], assignee_world["project"]
    _as(client, pm)
    task = client.post("/api/tasks", json={
        "title": "Clear", "project_id": project.id, "assigned_to": pm.id, "assignee_ids": [a1.id],
    }).json()
    resp = client.put(f"/api/tasks/{task['id']}", json={"assignee_ids": []})
    assert resp.status_code == 200
    assert resp.json().get("assignees") == []


def test_non_member_assignee_skipped(assignee_world, client, db):
    """An assignee outside the tenant is silently skipped, not a 500."""
    other = Tenant(name="Foreign Co", slug="foreign-co", plan="enterprise")
    db.add(other)
    db.commit()
    db.refresh(other)
    stranger = User(email="stranger-assignee@copilot.test", name="Stranger", hashed_password="x")
    db.add(stranger)
    db.commit()
    db.refresh(stranger)
    from app.models.tenant import TenantMembership as TM
    db.add(TM(user_id=stranger.id, tenant_id=other.id, role="owner"))
    stranger.active_tenant_id = other.id
    db.commit()

    pm, project = assignee_world["pm"], assignee_world["project"]
    _as(client, pm)
    resp = client.post("/api/tasks", json={
        "title": "Guard", "project_id": project.id, "assigned_to": pm.id,
        "assignee_ids": [stranger.id],
    })
    assert resp.status_code == 200
    assert resp.json().get("assignees") == []
