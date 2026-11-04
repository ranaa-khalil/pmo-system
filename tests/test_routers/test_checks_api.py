"""Tests for acceptance checks (Bayan build-tracker parity)."""
import pytest

import app.models  # noqa: F401
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User


@pytest.fixture()
def checks_world(client, db):
    tenant = Tenant(name="Checks Co", slug="checks-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-checks@copilot.test", name="PM", hashed_password="x",
              system_role="project_manager")
    db.add(pm)
    db.commit()
    db.refresh(pm)
    pm.active_tenant_id = tenant.id
    db.commit()
    db.add(TenantMembership(user_id=pm.id, tenant_id=tenant.id, role="owner"))
    project = Project(name="Checks Proj", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    item = BacklogItem(title="Feature with checks", project_id=project.id, tenant_id=tenant.id,
                       item_type="Feature", epic="E1")
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"tenant": tenant, "pm": pm, "project": project, "item": item}


def _as(client, user):
    from app.services.auth import create_access_token
    client.headers.update({"Authorization": f"Bearer {create_access_token(data={'sub': str(user.id)})}"})


def test_check_roundtrip_with_result(checks_world, client):
    pm, item = checks_world["pm"], checks_world["item"]
    _as(client, pm)
    s1 = client.post(f"/api/backlog/{item.id}/checks", json={"text": "A mood request creates a shelf"})
    assert s1.status_code == 201
    check = s1.json()
    assert check["result"] == "Not tested"
    resp = client.put(f"/api/checks/{check['id']}", json={"result": "Pass"})
    assert resp.status_code == 200
    assert resp.json()["result"] == "Pass"
    rows = client.get(f"/api/backlog/{item.id}/checks").json()
    assert len(rows) == 1
    assert rows[0]["result"] == "Pass"


def test_invalid_result_400(checks_world, client):
    pm, item = checks_world["pm"], checks_world["item"]
    _as(client, pm)
    check = client.post(f"/api/backlog/{item.id}/checks", json={"text": "Check"}).json()
    resp = client.put(f"/api/checks/{check['id']}", json={"result": "Maybe"})
    assert resp.status_code == 400


def test_order_autoincrements(checks_world, client):
    pm, item = checks_world["pm"], checks_world["item"]
    _as(client, pm)
    c1 = client.post(f"/api/backlog/{item.id}/checks", json={"text": "First"}).json()
    c2 = client.post(f"/api/backlog/{item.id}/checks", json={"text": "Second"}).json()
    assert c2["check_order"] == c1["check_order"] + 1


def test_empty_text_422(checks_world, client):
    pm, item = checks_world["pm"], checks_world["item"]
    _as(client, pm)
    resp = client.post(f"/api/backlog/{item.id}/checks", json={"text": "  "})
    assert resp.status_code == 422


def test_delete_check(checks_world, client):
    pm, item = checks_world["pm"], checks_world["item"]
    _as(client, pm)
    check = client.post(f"/api/backlog/{item.id}/checks", json={"text": "To delete"}).json()
    resp = client.delete(f"/api/checks/{check['id']}")
    assert resp.status_code == 204
    rows = client.get(f"/api/backlog/{item.id}/checks").json()
    assert len(rows) == 0


def test_cross_tenant_check_404(checks_world, client, db):
    other = Tenant(name="Other Checks", slug="other-checks", plan="enterprise")
    db.add(other)
    db.commit()
    db.refresh(other)
    stranger = User(email="stranger-checks@copilot.test", name="Stranger", hashed_password="x")
    db.add(stranger)
    db.commit()
    db.refresh(stranger)
    from app.models.tenant import TenantMembership as TM
    db.add(TM(user_id=stranger.id, tenant_id=other.id, role="owner"))
    stranger.active_tenant_id = other.id
    db.commit()
    _as(client, stranger)
    resp = client.get("/api/backlog/999999/checks")
    assert resp.status_code == 404
