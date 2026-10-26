"""Tests for the risks API — register CRUD scoped to a project.

GET /api/projects/{id}/risks lists the register (tenant + visibility filtered);
POST creates a risk (PM or super admin only); PUT updates status/severity;
risk score is computed server-side and returned with every row.
"""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.models.user import User


@pytest.fixture()
def api_world(client, db):
    """Logged-in PM with a project and one open risk."""
    tenant = Tenant(name="Risk API Co", slug="risk-api-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-riskapi@copilot.test", name="PM", hashed_password="x")
    db.add(pm)
    db.commit()
    db.refresh(pm)
    from app.models.tenant import TenantMembership
    db.add(TenantMembership(user_id=pm.id, tenant_id=tenant.id, role="owner"))
    project = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    risk = Risk(
        tenant_id=tenant.id, project_id=project.id,
        title="SSO integration slips", severity="High", probability="Medium",
        status="Open", owner_id=pm.id, source="manual",
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)

    from app.services.auth import create_access_token
    token = create_access_token(data={"sub": str(pm.id)})
    client.headers.update({"Authorization": f"Bearer {token}"})
    return {"tenant": tenant, "pm": pm, "project": project, "risk": risk}


def test_list_risks_returns_score(api_world, client):
    project = api_world["project"]
    resp = client.get(f"/api/projects/{project.id}/risks")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["score"] == 9  # High(3) × Medium(3)


def test_create_risk_pm_only(api_world, client):
    project = api_world["project"]
    resp = client.post(f"/api/projects/{project.id}/risks", json={
        "title": "Vendor API delay", "severity": "Critical", "probability": "Likely",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["score"] == 20  # Critical(5) × Likely(4)
    assert body["source"] == "manual"


def test_update_risk_status(api_world, client):
    risk = api_world["risk"]
    resp = client.put(f"/api/risks/{risk.id}", json={"status": "Mitigating"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "Mitigating"


def test_risk_visibility_scoped_to_project(api_world, client, db):
    """Risks from another tenant's project never leak."""
    other = Tenant(name="Other API Co", slug="other-api-co")
    db.add(other)
    db.commit()
    db.refresh(other)
    other_project = Project(name="Hidden", client_id=1, tenant_id=other.id)
    db.add(other_project)
    db.commit()
    db.refresh(other_project)
    db.add(Risk(tenant_id=other.id, project_id=other_project.id, title="Secret"))
    db.commit()

    resp = client.get(f"/api/projects/{api_world['project'].id}/risks")
    titles = [r["title"] for r in resp.json()]
    assert "Secret" not in titles
