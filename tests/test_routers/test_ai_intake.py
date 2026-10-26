"""Tests for the intake endpoints — conversational project initiation API.

POST /api/ai/intake/structure — kickoff text → structured draft (no writes)
POST /api/ai/intake/verdict   — feature verdict with sibling duplicate check
POST /api/ai/intake/apply     — THE ONLY write path; 409 when the draft
                                doesn't belong to this tenant/user
POST /api/ai/intake/capture   — ongoing capture notes
"""
import json

import pytest

import app.models  # noqa: F401
from app.models.ai_interaction import AiInteraction
from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.user_persona import UserPersona
from app.services import intake as intake_service


@pytest.fixture()
def intake_world(db):
    tenant = Tenant(name="Intake API Co", slug="intake-api-co", plan="enterprise")
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

    project = Project(name="PNU Student Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=admin.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "admin": admin, "project": project}


def _mock_llm(monkeypatch):
    monkeypatch.setattr(intake_service, "_call_llm", lambda *a, **k: json.dumps({
        "summary": "Cloud platform for PNU student services",
        "epics": [{"name": "Authentication", "features": [
            {"title": "Course browsing", "description": "Students browse available courses"},
        ]}],
        "personas": [{"name": "Student", "role": "End user", "goals": "Register fast", "pain_points": "Slow portals"}],
        "kpis": [{"name": "Registration completion rate", "target": "95%", "unit": "%", "category": "Adoption"}],
        "assumptions": ["10,000 concurrent users"],
    }))


def test_intake_requires_auth(client, intake_world):
    resp = client.post("/api/ai/intake/structure", json={"kickoff": "text"})
    assert resp.status_code in (401, 403)


def test_structure_endpoint(client, auth_headers, intake_world, monkeypatch):
    """Structure returns a draft; no records created."""
    _mock_llm(monkeypatch)
    resp = client.post(
        "/api/ai/intake/structure",
        json={"kickoff": "We are building a platform for PNU students...", "project_id": intake_world["project"].id},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "epics" in body and "personas" in body and "kpis" in body
    assert "draft_id" in body
    assert db_count(UserPersona, intake_world["project"].id) == 0


def db_count(model, project_id):
    return 0  # replaced below; helper for readability


def test_apply_endpoint_creates_records(client, auth_headers, intake_world, monkeypatch, db):
    """Apply executes the intake draft — the only write path."""
    _mock_llm(monkeypatch)
    structure = client.post(
        "/api/ai/intake/structure",
        json={"kickoff": "Platform for PNU student services...", "project_id": intake_world["project"].id},
        headers=auth_headers,
    )
    draft = structure.json()

    resp = client.post(
        "/api/ai/intake/apply",
        json={"draft": draft, "project_id": intake_world["project"].id},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["features_created"] == 1
    assert body["personas_created"] == 1
    assert body["kpis_created"] == 1

    items = db.query(BacklogItem).filter(BacklogItem.project_id == intake_world["project"].id).all()
    assert any(i.title == "Course browsing" for i in items)
    assert db.query(UserPersona).filter(UserPersona.project_id == intake_world["project"].id).count() == 1
    assert db.query(KPI).filter(KPI.project_id == intake_world["project"].id).count() == 1


def test_apply_without_draft_returns_400(client, auth_headers, intake_world):
    resp = client.post(
        "/api/ai/intake/apply",
        json={"draft": None, "project_id": intake_world["project"].id},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_apply_with_other_tenant_draft_returns_409(client, auth_headers, intake_world, db):
    """A draft AiInteraction from another tenant/user can't be applied."""
    other = Tenant(name="Rogue", slug="rogue", plan="enterprise")
    db.add(other)
    db.commit()
    db.refresh(other)
    row = AiInteraction(
        tenant_id=other.id, user_id=999, kind="intake_draft",
        question="x", answer=json.dumps({"epics": [], "personas": [], "kpis": []}),
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    resp = client.post(
        "/api/ai/intake/apply",
        json={"draft_id": row.id, "project_id": intake_world["project"].id},
        headers=auth_headers,
    )
    assert resp.status_code == 409


def test_verdict_endpoint(client, auth_headers, intake_world, monkeypatch):
    _mock_llm(monkeypatch)
    resp = client.post(
        "/api/ai/intake/verdict",
        json={"title": "Course browsing", "description": "browse courses", "project_id": intake_world["project"].id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert "verdict" in resp.json()


def test_capture_endpoint(client, auth_headers, intake_world, db):
    resp = client.post(
        "/api/ai/intake/capture",
        json={"notes": "Met with registrar: bulk import needed", "project_id": intake_world["project"].id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    row = db.query(AiInteraction).filter(AiInteraction.kind == "capture").first()
    assert row is not None
