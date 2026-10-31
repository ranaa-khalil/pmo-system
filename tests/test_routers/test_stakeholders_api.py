"""Tests for the stakeholders & RACI API — stakeholders, roles, assignments, traceability, users.

Stakeholders carry RACI types (R/A/C/I) — distinct from system roles.
Assignments map users to projects with RACI roles. All lookups are
tenant-filtered; users endpoint lists tenant members for assignment
dropdowns.
"""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.role import Role
from app.models.tenant import Tenant


@pytest.fixture()
def stake_world(client, db, auth_user):
    """The shared owner + a project in their tenant."""
    tenant = auth_user["tenant"]
    project = Project(name="Stakeholder P", client_id=1, tenant_id=tenant.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "user": auth_user["user"], "project": project}


# ── Stakeholders ─────────────────────────────────────────────────

def test_stakeholder_crud(stake_world, client):
    project = stake_world["project"]
    resp = client.post(f"/api/projects/{project.id}/stakeholders", json={
        "name": "Aldaana", "role_name": "Product Owner", "raci_type": "A",
    })
    assert resp.status_code == 201
    sid = resp.json()["id"]
    assert resp.json()["raci_type"] == "A"

    rows = client.get(f"/api/projects/{project.id}/stakeholders").json()
    assert len(rows) == 1

    resp = client.put(f"/api/stakeholders/{sid}", json={"raci_type": "R"})
    assert resp.status_code == 200
    assert resp.json()["raci_type"] == "R"

    resp = client.delete(f"/api/stakeholders/{sid}")
    assert resp.status_code == 204
    assert client.get(f"/api/projects/{project.id}/stakeholders").json() == []


def test_stakeholder_other_tenant_project_404(stake_world, client, db):
    other = Tenant(name="Other Stake", slug="other-stake", plan="team")
    db.add(other)
    db.commit()
    db.refresh(other)
    other_project = Project(name="Hidden", client_id=1, tenant_id=other.id)
    db.add(other_project)
    db.commit()
    db.refresh(other_project)

    resp = client.post(f"/api/projects/{other_project.id}/stakeholders", json={
        "name": "Sneaky", "role_name": "X",
    })
    assert resp.status_code == 404


# ── Roles ────────────────────────────────────────────────────────

def test_role_crud(stake_world, client):
    resp = client.post("/api/roles", json={"name": "Sponsor", "description": "Executive sponsor"})
    assert resp.status_code == 201
    rid = resp.json()["id"]

    rows = client.get("/api/roles").json()
    assert any(r["name"] == "Sponsor" for r in rows)

    resp = client.put(f"/api/roles/{rid}", json={"name": "Executive Sponsor"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Executive Sponsor"

    resp = client.delete(f"/api/roles/{rid}")
    assert resp.status_code == 204


# ── Assignments (RACI on projects) ───────────────────────────────

def test_assignment_flow(stake_world, client, db):
    project = stake_world["project"]
    user = stake_world["user"]
    role = Role(name="Project Manager")
    db.add(role)
    db.commit()
    db.refresh(role)

    resp = client.post(f"/api/projects/{project.id}/assignments", json={
        "user_id": user.id, "role_id": role.id, "project_id": project.id,
    })
    assert resp.status_code == 201

    rows = client.get(f"/api/projects/{project.id}/assignments").json()
    assert len(rows) == 1
    assert rows[0]["user_id"] == user.id

    assignment_id = rows[0]["id"]
    resp = client.delete(f"/api/assignments/{assignment_id}")
    assert resp.status_code == 204


def test_assignment_reassign_user(stake_world, client, db):
    """PUT /assignments/{id} swaps the assigned user, keeping the role."""
    project = stake_world["project"]
    user = stake_world["user"]
    from app.models.user import User

    role = Role(name="Tech Lead", tenant_id=stake_world["tenant"].id)
    db.add(role)
    other = User(email="reassign@example.com", name="Reassign Target",
                 hashed_password="x", system_role="member", active_tenant_id=stake_world["tenant"].id)
    db.add_all([role, other])
    db.commit()
    db.refresh(role)
    db.refresh(other)

    resp = client.post(f"/api/projects/{project.id}/assignments", json={
        "user_id": user.id, "role_id": role.id, "project_id": project.id,
    })
    assert resp.status_code == 201
    assignment_id = resp.json()["id"]

    # Swap the user on the same assignment
    resp = client.put(f"/api/assignments/{assignment_id}", json={"user_id": other.id})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == other.id
    assert resp.json()["role_id"] == role.id

    rows = client.get(f"/api/projects/{project.id}/assignments").json()
    assert len(rows) == 1
    assert rows[0]["user_id"] == other.id
    assert rows[0]["role_name"] == "Tech Lead"


def test_assignment_change_role(stake_world, client, db):
    """PUT /assignments/{id} changes the RACI role on the same user."""
    project = stake_world["project"]
    user = stake_world["user"]
    role_a = Role(name="QA Lead", tenant_id=stake_world["tenant"].id)
    role_b = Role(name="DevOps Lead", tenant_id=stake_world["tenant"].id)
    db.add_all([role_a, role_b])
    db.commit()
    db.refresh(role_a)
    db.refresh(role_b)

    resp = client.post(f"/api/projects/{project.id}/assignments", json={
        "user_id": user.id, "role_id": role_a.id, "project_id": project.id,
    })
    assert resp.status_code == 201
    assignment_id = resp.json()["id"]

    resp = client.put(f"/api/assignments/{assignment_id}", json={"role_id": role_b.id})
    assert resp.status_code == 200
    assert resp.json()["role_id"] == role_b.id

    rows = client.get(f"/api/projects/{project.id}/assignments").json()
    assert rows[0]["role_name"] == "DevOps Lead"


def test_assignment_update_duplicate_400(stake_world, client, db):
    """Updating onto an existing user+role pair is rejected (duplicate)."""
    project = stake_world["project"]
    user = stake_world["user"]
    role_a = Role(name="UX Designer")
    role_b = Role(name="Product Owner")
    db.add_all([role_a, role_b])
    db.commit()
    db.refresh(role_a)
    db.refresh(role_b)

    a1 = client.post(f"/api/projects/{project.id}/assignments", json={
        "user_id": user.id, "role_id": role_a.id, "project_id": project.id,
    }).json()["id"]
    a2 = client.post(f"/api/projects/{project.id}/assignments", json={
        "user_id": user.id, "role_id": role_b.id, "project_id": project.id,
    }).json()["id"]

    # a2 moving onto role_a would duplicate a1
    resp = client.put(f"/api/assignments/{a2}", json={"role_id": role_a.id})
    assert resp.status_code == 400
    assert "exists" in resp.json()["detail"]


def test_assignment_update_no_change(stake_world, client, db):
    """A PUT with no effective change is a no-op success."""
    project = stake_world["project"]
    user = stake_world["user"]
    role = Role(name="PMO")
    db.add(role)
    db.commit()
    db.refresh(role)

    assignment_id = client.post(f"/api/projects/{project.id}/assignments", json={
        "user_id": user.id, "role_id": role.id, "project_id": project.id,
    }).json()["id"]

    resp = client.put(f"/api/assignments/{assignment_id}", json={})
    assert resp.status_code == 200
    assert resp.json()["message"] == "No change"


# ── Users (tenant member list) ───────────────────────────────────

def test_list_users_for_assignment(stake_world, client, db):
    resp = client.get("/api/users")
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert "test@pmo.test" in emails


def test_create_user_via_stakeholders(stake_world, client, db):
    """POST /users creates a tenant member (for assignment dropdowns)."""
    resp = client.post("/api/users", json={
        "email": "new@stake.example.com", "name": "New PM", "password": "Stake12345!",
    })
    assert resp.status_code == 201
    assert resp.json()["email"] == "new@stake.example.com"
    # The new user is a member of the caller's tenant (created there)
    from app.models.tenant import TenantMembership
    m = db.query(TenantMembership).filter(
        TenantMembership.tenant_id == stake_world["tenant"].id,
    ).all()
    assert any(mm.user_id == resp.json()["id"] for mm in m)


# ── Traceability ─────────────────────────────────────────────────

def test_traceability_structure(stake_world, client, db):
    """Traceability chains requirements → roadmap → KPIs → releases."""
    project = stake_world["project"]
    from app.models.backlog_item import BacklogItem
    from app.models.kpi import KPI
    from app.models.release import Release

    item = BacklogItem(tenant_id=stake_world["tenant"].id, project_id=project.id, title="SSO login", current_phase="Requirements")
    db.add(item)
    db.add(KPI(tenant_id=stake_world["tenant"].id, project_id=project.id, name="Adoption", target_value="80", current_value="10"))
    release = Release(tenant_id=stake_world["tenant"].id, project_id=project.id, version="1.0.0", name="R1", status="Planned")
    db.add(release)
    db.commit()

    resp = client.get(f"/api/projects/{project.id}/traceability")
    assert resp.status_code == 200
    data = resp.json()
    assert "backlog_items" in data
    assert any(i["title"] == "SSO login" for i in data["backlog_items"])
