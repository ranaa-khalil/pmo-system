"""Tests for saved project views — GitHub Boards parity (R7).

Views capture name + filters (JSON) per project; shared views are visible to
everyone with project access, private only to their creator. Deletion is
creator/PM/tenant-admin only.
"""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.project_view import ProjectView
from app.models.tenant import Tenant
from app.models.user import User


@pytest.fixture()
def views_world(client, db):
    """Logged-in PM with a project and one shared view."""
    tenant = Tenant(name="Views Co", slug="views-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-views@copilot.test", name="PM", hashed_password="x",
              system_role="project_manager")
    db.add(pm)
    db.commit()
    db.refresh(pm)
    pm.active_tenant_id = tenant.id
    db.commit()
    from app.models.tenant import TenantMembership
    db.add(TenantMembership(user_id=pm.id, tenant_id=tenant.id, role="owner"))
    project = Project(name="Views Proj", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    view = ProjectView(
        tenant_id=tenant.id, project_id=project.id, name="Blocked only",
        filters='{"status": "Blocked"}', shared=True, created_by=pm.id,
    )
    db.add(view)
    db.commit()
    db.refresh(view)

    from app.services.auth import create_access_token
    token = create_access_token(data={"sub": str(pm.id)})
    client.headers.update({"Authorization": f"Bearer {token}"})
    return {"tenant": tenant, "pm": pm, "project": project, "view": view}


def test_list_views(views_world, client):
    project = views_world["project"]
    resp = client.get(f"/api/projects/{project.id}/views")
    assert resp.status_code == 200
    rows = resp.json()
    assert any(v["name"] == "Blocked only" for v in rows)
    saved = next(v for v in rows if v["name"] == "Blocked only")
    assert saved["filters"] == {"status": "Blocked"}


def test_create_view_with_filters(views_world, client):
    project = views_world["project"]
    resp = client.post(f"/api/projects/{project.id}/views", json={
        "name": "High priority board", "filters": {"search": "api", "group_by": "epic"}, "shared": False,
    })
    assert resp.status_code == 201
    row = resp.json()
    assert row["name"] == "High priority board"
    assert row["filters"] == {"search": "api", "group_by": "epic"}
    assert row["shared"] is False


def test_create_view_requires_manager(views_world, client, db):
    project = views_world["project"]
    member = User(email="member-views@copilot.test", name="Member", hashed_password="x")
    db.add(member)
    db.commit()
    db.refresh(member)
    from app.services.auth import create_access_token
    client.headers.update({"Authorization": f"Bearer {create_access_token(data={'sub': str(member.id)})}"})
    resp = client.post(f"/api/projects/{project.id}/views", json={"name": "Nope"})
    assert resp.status_code == 403


def test_private_view_scoped_to_creator(views_world, client, db):
    """A private view created by the PM is not visible to another member."""
    tenant, project, pm = views_world["tenant"], views_world["project"], views_world["pm"]
    private = ProjectView(
        tenant_id=tenant.id, project_id=project.id, name="PM private",
        filters="{}", shared=False, created_by=pm.id,
    )
    db.add(private)
    db.commit()
    member = User(email="member2-views@copilot.test", name="Member2", hashed_password="x")
    db.add(member)
    db.commit()
    db.refresh(member)
    from app.models.tenant import TenantMembership
    db.add(TenantMembership(user_id=member.id, tenant_id=tenant.id, role="member"))
    db.commit()
    from app.services.auth import create_access_token
    client.headers.update({"Authorization": f"Bearer {create_access_token(data={'sub': str(member.id)})}"})
    rows = client.get(f"/api/projects/{project.id}/views").json()
    names = {v["name"] for v in rows}
    assert "PM private" not in names
    assert "Blocked only" in names  # shared stays visible


def test_delete_own_view(views_world, client, db):
    tenant, project, pm = views_world["tenant"], views_world["project"], views_world["pm"]
    mine = ProjectView(tenant_id=tenant.id, project_id=project.id, name="Mine", filters=None, shared=False, created_by=pm.id)
    db.add(mine)
    db.commit()
    db.refresh(mine)
    resp = client.delete(f"/api/views/{mine.id}")
    assert resp.status_code == 204
    assert db.query(ProjectView).filter(ProjectView.id == mine.id).first() is None


def test_delete_other_members_view_403(views_world, client, db):
    """A member cannot delete a view they didn't create."""
    project = views_world["project"]
    member = User(email="member3-views@copilot.test", name="Member3", hashed_password="x")
    db.add(member)
    db.commit()
    db.refresh(member)
    from app.services.auth import create_access_token
    client.headers.update({"Authorization": f"Bearer {create_access_token(data={'sub': str(member.id)})}"})
    resp = client.delete(f"/api/views/{views_world['view'].id}")
    assert resp.status_code == 403


def test_views_tenant_scoped(views_world, client, db):
    """Views of another tenant's project are not listed."""
    other_tenant = Tenant(name="Other Views Co", slug="other-views-co", plan="enterprise")
    db.add(other_tenant)
    db.commit()
    db.refresh(other_tenant)
    other = Project(name="Other Proj", client_id=1, tenant_id=other_tenant.id)
    db.add(other)
    db.commit()
    db.refresh(other)
    ProjectView(tenant_id=other_tenant.id, project_id=other.id, name="Foreign", filters=None, shared=True)
    db.commit()
    rows = client.get(f"/api/projects/{views_world['project'].id}/views").json()
    assert all(v["name"] != "Foreign" for v in rows)
