"""Tests for project_type on Project — lifecycle templates as data.

project_type selects the template (software default). The API exposes
project_type on create/update and /lifecycle/{type} returns the template
vocabulary for the UI.
"""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User


@pytest.fixture()
def pt_world(db):
    tenant = Tenant(name="PT Co", slug="pt-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    admin = db.query(User).filter(User.email == "test@pmo.test").first()
    if not admin:
        admin = User(email="test@pmo.test", name="Admin", hashed_password="x", system_role="super_admin")
        db.add(admin)
        db.commit()
    admin.active_tenant_id = tenant.id
    db.add(TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="owner"))
    db.commit()
    db.refresh(admin)
    return {"tenant": tenant, "admin": admin}


def test_project_type_column_defaults_software(db, pt_world):
    project = Project(name="P1", client_id=1, tenant_id=pt_world["tenant"].id, project_manager_id=pt_world["admin"].id)
    db.add(project)
    db.commit()
    db.refresh(project)
    assert project.project_type == "software"


def test_project_type_accepts_ai(db, pt_world):
    project = Project(name="P2", client_id=1, tenant_id=pt_world["tenant"].id, project_manager_id=pt_world["admin"].id, project_type="ai")
    db.add(project)
    db.commit()
    db.refresh(project)
    assert project.project_type == "ai"


def test_lifecycle_endpoint_returns_template(client, auth_headers, pt_world):
    resp = client.get("/api/lifecycle/ai", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "AI Project (CPMAI)"
    assert "Data Readiness" in body["item_phases"]
    assert body["gate_roles"]["Evaluation"] == "Product Manager"


def test_lifecycle_endpoint_defaults_for_unknown(client, auth_headers):
    resp = client.get("/api/lifecycle/unknown-type", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Software"
