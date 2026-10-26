"""Tests for the intake service — conversational project initiation.

structure_intake turns a kickoff paragraph/doc into a structured draft
(epics, features, personas, KPIs — with source links). feature_verdict
answers "does this feature exist / fit an epic / is it new" with a
sibling-project duplicate check. apply_intake executes nothing until the
human confirms; on apply it creates real records with traceability stored
at birth.
"""
import json

import pytest

import app.models  # noqa: F401
from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.user_persona import UserPersona
from app.services import intake

KICKOFF = """
We are building a cloud platform for PNU to manage student services.
Students log in with SSO and browse available courses. Faculty members
approve course registrations and publish grades. The platform must handle
10,000 concurrent users and we measure success by registration completion
rate above 95% and login time under 2 seconds.
"""


@pytest.fixture()
def intake_world(db):
    tenant = Tenant(name="Intake Co", slug="intake-co", plan="enterprise")
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

    # Existing item for verdict tests
    item = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="SSO login",
        epic="Authentication", current_phase="Requirements", status="Draft",
        item_type="Feature",
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    # A sibling project with a near-duplicate
    sibling = Project(name="CloudGate", client_id=1, tenant_id=tenant.id, project_manager_id=admin.id)
    db.add(sibling)
    db.commit()
    db.refresh(sibling)
    dup = BacklogItem(
        tenant_id=tenant.id, project_id=sibling.id, title="SSO login page",
        epic="Auth", current_phase="Development", status="In Progress",
        item_type="Feature",
    )
    db.add(dup)
    db.commit()

    return {"tenant": tenant, "admin": admin, "project": project, "item": item, "sibling": sibling}


def _fake_llm_response():
    return json.dumps({
        "summary": "Cloud platform for PNU student services",
        "epics": [
            {
                "name": "Authentication",
                "features": [
                    {"title": "SSO login", "description": "Single sign-on for students and faculty"},
                    {"title": "Course browsing", "description": "Students browse available courses"},
                ],
            },
            {
                "name": "Grades",
                "features": [
                    {"title": "Grade publishing", "description": "Faculty publish grades per course"},
                ],
            },
        ],
        "personas": [
            {"name": "Student", "role": "End user", "goals": "Register for courses quickly", "pain_points": "Slow portals"},
            {"name": "Faculty Member", "role": "Approver", "goals": "Approve registrations fast", "pain_points": "Manual approvals"},
        ],
        "kpis": [
            {"name": "Registration completion rate", "target": "95%", "unit": "%", "category": "Adoption"},
            {"name": "Login time", "target": "< 2s", "unit": "s", "category": "Performance"},
        ],
        "assumptions": ["10,000 concurrent users", "SSO provider already exists"],
    })


def test_structure_intake_returns_draft(db, intake_world, monkeypatch):
    """structure_intake calls the LLM and returns a structured draft — no records written."""
    monkeypatch.setattr(intake, "_call_llm", lambda *a, **k: _fake_llm_response())

    draft = intake.structure_intake(db, intake_world["admin"], intake_world["tenant"], KICKOFF)

    assert draft["summary"].startswith("Cloud platform")
    assert len(draft["epics"]) == 2
    assert len(draft["personas"]) == 2
    assert len(draft["kpis"]) == 2
    assert draft["assumptions"]

    # Nothing written yet
    assert db.query(UserPersona).filter(UserPersona.project_id == intake_world["project"].id).count() == 0
    assert db.query(KPI).filter(KPI.project_id == intake_world["project"].id).count() == 0


def test_apply_intake_creates_records(db, intake_world, monkeypatch):
    """apply_intake creates epics+features+personas+KPIs with traceability."""
    monkeypatch.setattr(intake, "_call_llm", lambda *a, **k: _fake_llm_response())
    draft = intake.structure_intake(db, intake_world["admin"], intake_world["tenant"], KICKOFF)

    result = intake.apply_intake(db, intake_world["admin"], intake_world["tenant"], intake_world["project"], draft)

    personas = db.query(UserPersona).filter(UserPersona.project_id == intake_world["project"].id).all()
    kpis = db.query(KPI).filter(KPI.project_id == intake_world["project"].id).all()
    items = db.query(BacklogItem).filter(BacklogItem.project_id == intake_world["project"].id).all()

    assert len(personas) == 2
    assert len(kpis) == 2
    # 1 seeded item + 2 new features (the draft's "SSO login" is correctly
    # skipped as a duplicate of the seeded item)
    assert len(items) == 3
    assert result["features_created"] == 2
    assert result["features_skipped"] == 1
    assert result["personas_created"] == 2
    assert result["kpis_created"] == 2


def test_feature_verdict_exists(db, intake_world, monkeypatch):
    """A feature that already exists → verdict 'exists' with the record id."""
    monkeypatch.setattr(intake, "_call_llm", lambda *a, **k: json.dumps({
        "verdict": "exists", "confidence": 0.9, "reasoning": "Matches the existing SSO login item",
    }))
    verdict = intake.feature_verdict(
        db, intake_world["tenant"], intake_world["project"],
        "SSO login", "Single sign-on for students",
    )
    assert verdict["verdict"] == "exists"
    assert verdict["confidence"] >= 0.8
    assert verdict["existing_item_id"] == intake_world["item"].id


def test_feature_verdict_flags_sibling_duplicate(db, intake_world):
    """The duplicate check scans sibling projects even before the LLM call.

    'Login page' doesn't exist in this project; it matches the sibling
    CloudGate item 'SSO login page' → surfaced as a duplicate warning.
    """
    verdict = intake.feature_verdict(
        db, intake_world["tenant"], intake_world["project"],
        "Login page", "student login",
        llm_fn=lambda *a, **k: json.dumps({
            "verdict": "new", "confidence": 0.6, "reasoning": "",
        }),
    )
    # The service must surface the sibling duplicate found by name matching
    assert verdict["sibling_duplicates"], f"expected sibling duplicates, got: {verdict}"
    assert verdict["sibling_duplicates"][0]["project"] == "CloudGate"


def test_capture_ongoing(db, intake_world):
    """capture_ongoing records meeting/chat notes as an AiInteraction (source at birth)."""
    from app.models.ai_interaction import AiInteraction

    interaction = intake.capture_ongoing(
        db, intake_world["admin"], intake_world["tenant"], intake_world["project"],
        "Met with registrar: they need bulk import of courses from Excel",
    )
    row = db.query(AiInteraction).filter(AiInteraction.id == interaction.id).first()
    assert row.kind == "capture"
    assert row.project_id == intake_world["project"].id
    assert "bulk import" in row.question


def test_apply_intake_skips_existing_titles(db, intake_world, monkeypatch):
    """apply_intake doesn't duplicate a feature whose title already exists in the project."""
    monkeypatch.setattr(intake, "_call_llm", lambda *a, **k: _fake_llm_response())
    draft = intake.structure_intake(db, intake_world["admin"], intake_world["tenant"], KICKOFF)

    result = intake.apply_intake(db, intake_world["admin"], intake_world["tenant"], intake_world["project"], draft)
    # "SSO login" already exists in the project — not created twice
    assert result["features_skipped"] == 1
    items = db.query(BacklogItem).filter(BacklogItem.project_id == intake_world["project"].id)
    sso = items.filter(BacklogItem.title == "SSO login").all()
    assert len(sso) == 1
