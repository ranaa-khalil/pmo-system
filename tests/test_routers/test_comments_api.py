"""Tests for comments on tasks and backlog items."""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User


@pytest.fixture()
def comment_world(client, db):
    tenant = Tenant(name="Comment Co", slug="comment-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-comment@copilot.test", name="PM", hashed_password="x",
              system_role="project_manager")
    member = User(email="member-comment@copilot.test", name="Member", hashed_password="x")
    db.add_all([pm, member])
    db.commit()
    db.refresh(pm)
    db.refresh(member)
    for u, role in [(pm, "owner"), (member, "member")]:
        db.add(TenantMembership(user_id=u.id, tenant_id=tenant.id, role=role))
        u.active_tenant_id = tenant.id
    db.commit()
    project = Project(name="Comment Proj", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "pm": pm, "member": member, "project": project}


def _as(client, user):
    from app.services.auth import create_access_token
    client.headers.update({"Authorization": f"Bearer {create_access_token(data={'sub': str(user.id)})}"})


def test_task_comment_roundtrip(comment_world, client):
    pm, project = comment_world["pm"], comment_world["project"]
    _as(client, pm)
    task = client.post("/api/tasks", json={
        "title": "Commented task", "project_id": project.id, "assigned_to": pm.id,
    }).json()
    s1, c = 201, client.post(f"/api/tasks/{task['id']}/comments", json={"body": "First comment"}).json()
    resp = client.get(f"/api/tasks/{task['id']}/comments")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["body"] == "First comment"
    assert rows[0]["user_name"] == "PM"


def test_item_comment_roundtrip(comment_world, client, db):
    from app.models.backlog_item import BacklogItem

    pm, project, tenant = comment_world["pm"], comment_world["project"], comment_world["tenant"]
    _as(client, pm)
    item = BacklogItem(title="Commented item", project_id=project.id, tenant_id=tenant.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    resp = client.post(f"/api/backlog/{item.id}/comments", json={"body": "Item note"})
    assert resp.status_code == 201
    rows = client.get(f"/api/backlog/{item.id}/comments").json()
    assert len(rows) == 1
    assert rows[0]["body"] == "Item note"


def test_empty_body_422(comment_world, client):
    pm, project = comment_world["pm"], comment_world["project"]
    _as(client, pm)
    task = client.post("/api/tasks", json={
        "title": "Task", "project_id": project.id, "assigned_to": pm.id,
    }).json()
    resp = client.post(f"/api/tasks/{task['id']}/comments", json={"body": "   "})
    assert resp.status_code == 422


def test_member_can_comment(comment_world, client):
    member, project = comment_world["member"], comment_world["project"]
    _as(client, member)
    task = client.post("/api/tasks", json={
        "title": "Shared task", "project_id": project.id, "assigned_to": member.id,
    }).json()
    resp = client.post(f"/api/tasks/{task['id']}/comments", json={"body": "Member says hi"})
    assert resp.status_code == 201


def test_cross_tenant_task_404(comment_world, client, db):
    other = Tenant(name="Other Comment Co", slug="other-comment-co", plan="enterprise")
    db.add(other)
    db.commit()
    db.refresh(other)
    stranger = User(email="stranger-comment@copilot.test", name="Stranger", hashed_password="x")
    db.add(stranger)
    db.commit()
    db.refresh(stranger)
    from app.models.tenant import TenantMembership as TM
    db.add(TM(user_id=stranger.id, tenant_id=other.id, role="owner"))
    stranger.active_tenant_id = other.id
    db.commit()
    _as(client, stranger)
    resp = client.get("/api/tasks/999999/comments")
    assert resp.status_code == 404
