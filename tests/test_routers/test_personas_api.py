"""Tests for the personas & test-accounts API — per-project CRUD.

Personas are project-scoped end-user archetypes; test accounts hold per-
environment credentials. Writes require project-manager authority (403 for
outsiders); lists are tenant-filtered so other tenants' rows never leak.
"""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User


@pytest.fixture()
def persona_world(client, db, auth_user):
    """The shared PM + their project."""
    tenant = auth_user["tenant"]
    user = auth_user["user"]
    project = Project(name="Persona P", client_id=1, tenant_id=tenant.id, project_manager_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "user": user, "project": project}


def test_create_and_list_persona(persona_world, client):
    project = persona_world["project"]
    resp = client.post(f"/api/projects/{project.id}/personas", json={
        "project_id": project.id, "name": "Student", "role": "End User",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Student"

    rows = client.get(f"/api/projects/{project.id}/personas").json()
    assert len(rows) == 1
    assert rows[0]["role"] == "End User"


def test_update_persona(persona_world, client):
    project = persona_world["project"]
    pid = client.post(f"/api/projects/{project.id}/personas", json={
        "project_id": project.id, "name": "Faculty",
    }).json()["id"]
    resp = client.put(f"/api/projects/{project.id}/personas/{pid}", json={"name": "Faculty Member"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Faculty Member"


def test_delete_persona(persona_world, client):
    project = persona_world["project"]
    pid = client.post(f"/api/projects/{project.id}/personas", json={
        "project_id": project.id, "name": "Temp",
    }).json()["id"]
    resp = client.delete(f"/api/projects/{project.id}/personas/{pid}")
    assert resp.status_code == 200
    assert client.get(f"/api/projects/{project.id}/personas").json() == []


def test_persona_other_tenant_project_404(persona_world, client, db):
    """Creating a persona on another tenant's project 404s (tenant-scoped)."""
    other = Tenant(name="Other Personas", slug="other-personas", plan="team")
    db.add(other)
    db.commit()
    db.refresh(other)
    other_project = Project(name="Hidden P", client_id=1, tenant_id=other.id)
    db.add(other_project)
    db.commit()
    db.refresh(other_project)

    resp = client.post(f"/api/projects/{other_project.id}/personas", json={
        "project_id": other_project.id, "name": "Sneaky",
    })
    assert resp.status_code == 404


def test_persona_member_cannot_create(persona_world, client, db):
    """A plain member without project authority gets 403."""
    from app.services.auth import create_access_token

    member = User(email="m@persona.example.com", name="M", hashed_password="x", system_role="member", active_tenant_id=persona_world["tenant"].id)
    db.add(member)
    db.commit()
    db.refresh(member)
    token = create_access_token({"sub": str(member.id)})

    project = persona_world["project"]
    resp = client.post(f"/api/projects/{project.id}/personas", json={
        "project_id": project.id, "name": "Nope",
    }, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_test_accounts_crud(persona_world, client):
    project = persona_world["project"]
    resp = client.post(f"/api/projects/{project.id}/test-accounts", json={
        "project_id": project.id, "environment": "UAT", "username": "admin@uat", "password_hint": "Hint@1",
    })
    assert resp.status_code == 201
    aid = resp.json()["id"]

    rows = client.get(f"/api/projects/{project.id}/test-accounts").json()
    assert len(rows) == 1
    assert rows[0]["environment"] == "UAT"

    resp = client.put(f"/api/projects/{project.id}/test-accounts/{aid}", json={"role": "Super Admin"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "Super Admin"

    resp = client.delete(f"/api/projects/{project.id}/test-accounts/{aid}")
    assert resp.status_code == 200
    assert client.get(f"/api/projects/{project.id}/test-accounts").json() == []
