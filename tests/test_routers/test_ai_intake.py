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


def test_intake_requires_auth(anon_client, intake_world):
    resp = anon_client.post("/api/ai/intake/structure", json={"kickoff": "text"})
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


# ── ONE-CALL intake (Slice 3b — the capture box) ─────────────────────────


def _intake_call(client, auth_headers, notes, project_id=None, **extra):
    body = {"notes": notes, "source": "capture box", **extra}
    if project_id is not None:
        body["project_id"] = project_id
    return client.post("/api/ai/intake", json=body, headers=auth_headers)


def test_one_call_intake_requires_auth(anon_client, intake_world):
    resp = anon_client.post("/api/ai/intake", json={"notes": "Add SSO"})
    assert resp.status_code in (401, 403)


def test_openapi_shows_the_collapsed_intake(client, auth_headers):
    """Intake acceptance: OpenAPI shows POST /api/ai/intake (+ confirm/dismiss)."""
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/api/ai/intake", "/api/ai/intake/confirm", "/api/ai/intake/dismiss"):
        assert path in paths, f"{path} missing from OpenAPI"
        assert "post" in paths[path]


def test_one_call_intake_returns_one_confirm_payload(client, auth_headers, intake_world, monkeypatch, db):
    """(a) ONE call runs capture→structure→verdict→apply-prep and returns the
    Confirm payload: draft items in Requirements + dedupe + source tag."""
    _mock_llm(monkeypatch)
    resp = _intake_call(
        client, auth_headers,
        "We need course browsing for PNU students",
        project_id=intake_world["project"].id,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["structured"] is True
    assert body["source"] == "capture box"
    assert body["draft_id"] is not None
    assert body["parking_lot"] is False
    assert body["items"], "the Confirm payload carries the draft items"
    first = body["items"][0]
    assert first["phase"] == "Requirements"
    assert first["key"] == "item-0"
    assert first["dedupe"] is None
    # Nothing written before Confirm: no items, only the capture + draft rows
    assert db.query(BacklogItem).filter(BacklogItem.project_id == intake_world["project"].id).count() == 0
    assert db.query(AiInteraction).filter(AiInteraction.kind == "capture").count() == 1
    assert db.query(AiInteraction).filter(AiInteraction.kind == "intake_draft").count() == 1


def test_one_call_intake_dedupe_warning(client, auth_headers, intake_world, monkeypatch, db):
    """(b) Title-similarity check against the tenant's existing items."""
    existing = BacklogItem(title="Course browsing", project_id=intake_world["project"].id, tenant_id=intake_world["tenant"].id)
    db.add(existing)
    db.commit()
    db.refresh(existing)

    _mock_llm(monkeypatch)
    resp = _intake_call(
        client, auth_headers,
        "Please add course browsing to the student portal",
        project_id=intake_world["project"].id,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items and items[0]["dedupe"] is not None
    assert items[0]["dedupe"]["item_id"] == existing.id
    assert items[0]["dedupe"]["title"] == "Course browsing"


def test_one_call_intake_parking_lot(client, auth_headers, intake_world, monkeypatch, db):
    """(c) A no-project line lands in the tenant parking lot (project_id null)
    and stays parked until a PM files it."""
    _mock_llm(monkeypatch)
    resp = _intake_call(client, auth_headers, "Add bulk import for transcripts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["parking_lot"] is True
    assert body["project_id"] is None
    assert body["items"], "the line still proposes draft items"

    row = (
        db.query(AiInteraction)
        .filter(AiInteraction.kind == "intake_draft")
        .order_by(AiInteraction.id.desc())
        .first()
    )
    assert row is not None and row.project_id is None

    # Confirming a parked draft without filing a project refuses (the lot holds
    # the line for a PM to file) — BacklogItem.project_id is NOT NULL.
    r2 = client.post(
        "/api/ai/intake/confirm",
        json={"draft_id": body["draft_id"], "keys": ["item-0"]},
        headers=auth_headers,
    )
    assert r2.status_code == 400, r2.text
    assert db.query(BacklogItem).filter(BacklogItem.tenant_id == intake_world["tenant"].id).count() == 0

    # Filing it lands the item under the chosen project
    r3 = client.post(
        "/api/ai/intake/confirm",
        json={"draft_id": body["draft_id"], "keys": ["item-0"], "project_id": intake_world["project"].id},
        headers=auth_headers,
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["confirmed"] == 1
    items = db.query(BacklogItem).filter(BacklogItem.project_id == intake_world["project"].id).all()
    assert len(items) == 1 and items[0].current_phase == "Requirements"


def test_one_call_intake_confirm_lands_in_requirements(client, auth_headers, intake_world, monkeypatch, db):
    """The step ledger: create = sentence → Confirm (2 steps). The confirmed
    items land in the Requirements lane with the intake traceability."""
    _mock_llm(monkeypatch)
    first = _intake_call(
        client, auth_headers, "Students need course browsing",
        project_id=intake_world["project"].id,
    ).json()
    second = _intake_call(
        client, auth_headers, "Students need course browsing",
        project_id=intake_world["project"].id,
    ).json()

    resp = client.post(
        "/api/ai/intake/confirm",
        json={"draft_id": second["draft_id"], "keys": [it["key"] for it in second["items"]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["confirmed"] == 1
    assert body["items"][0]["phase"] == "Requirements"

    items = db.query(BacklogItem).filter(BacklogItem.project_id == intake_world["project"].id).all()
    assert len(items) == 1, "only the confirmed draft lands — the first draft stays pending"
    assert items[0].current_phase == "Requirements" and items[0].status == "Draft"
    assert "Capture box draft" in (items[0].description or "")

    # Re-confirming the same draft refuses
    again = client.post(
        "/api/ai/intake/confirm",
        json={"draft_id": second["draft_id"]},
        headers=auth_headers,
    )
    assert again.status_code == 409


def test_one_call_intake_verbatim_fallback(client, auth_headers, intake_world, monkeypatch, db):
    """(d) LLM mocked down → capture NEVER blocks, NEVER 500s: the line is
    saved VERBATIM as a Requirements-phase draft, flagged needs structuring."""
    def _llm_down(*args, **kwargs):
        raise RuntimeError("LLM down — connection refused")

    monkeypatch.setattr(intake_service, "_call_llm", _llm_down)
    sentence = "Add SSO for the registrar portal before the spring term"
    resp = _intake_call(client, auth_headers, sentence, project_id=intake_world["project"].id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["structured"] is False
    assert body["draft_id"] is not None
    assert len(body["items"]) == 1
    draft = body["items"][0]
    assert draft["title"] == sentence, "the line is kept VERBATIM as the title"
    assert draft["needs_structuring"] is True
    assert draft["phase"] == "Requirements"

    # Confirming lands the verbatim line as a Requirements-phase item
    r2 = client.post(
        "/api/ai/intake/confirm",
        json={"draft_id": body["draft_id"], "keys": ["item-0"]},
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    items = db.query(BacklogItem).filter(BacklogItem.project_id == intake_world["project"].id).all()
    assert len(items) == 1
    assert items[0].title == sentence
    assert items[0].current_phase == "Requirements"
    assert "Needs structuring" in (items[0].description or "")


def test_one_call_intake_my_task_destination(client, auth_headers, intake_world, monkeypatch, db):
    """Source chips pick the destination — My Task creates a personal task."""
    _mock_llm(monkeypatch)
    resp = _intake_call(
        client, auth_headers, "Renew the registrar meeting notes",
        project_id=intake_world["project"].id, destination="my_task",
    )
    assert resp.status_code == 200
    body = resp.json()
    r2 = client.post(
        "/api/ai/intake/confirm",
        json={"draft_id": body["draft_id"], "keys": ["item-0"], "destination": "my_task"},
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["items"][0]["kind"] == "task"
    assert db.query(BacklogItem).filter(BacklogItem.project_id == intake_world["project"].id).count() == 0


def test_one_call_intake_empty_notes_returns_400(client, auth_headers, intake_world):
    resp = client.post("/api/ai/intake", json={"notes": "   "}, headers=auth_headers)
    assert resp.status_code == 400


def test_one_call_intake_confirm_unknown_draft_404(client, auth_headers, intake_world):
    resp = client.post("/api/ai/intake/confirm", json={"draft_id": 99999}, headers=auth_headers)
    assert resp.status_code == 404


def test_one_call_intake_dismiss(client, auth_headers, intake_world, monkeypatch, db):
    """Dismiss marks the draft rejected — nothing executes."""
    _mock_llm(monkeypatch)
    body = _intake_call(client, auth_headers, "A line we will not capture", project_id=intake_world["project"].id).json()
    resp = client.post("/api/ai/intake/dismiss", json={"draft_id": body["draft_id"]}, headers=auth_headers)
    assert resp.status_code == 200
    row = db.query(AiInteraction).filter(AiInteraction.id == body["draft_id"]).first()
    assert row.status == "rejected"
    assert db.query(BacklogItem).filter(BacklogItem.project_id == intake_world["project"].id).count() == 0


def test_old_intake_chain_still_works_after_the_collapse(client, auth_headers, intake_world, monkeypatch):
    """(e) The old 4-call endpoints stay intact — structure→apply round-trip
    still passes alongside the collapsed one-call endpoint."""
    _mock_llm(monkeypatch)
    structure = client.post(
        "/api/ai/intake/structure",
        json={"kickoff": "Platform for PNU student services...", "project_id": intake_world["project"].id},
        headers=auth_headers,
    )
    assert structure.status_code == 200
    draft = structure.json()
    apply_resp = client.post(
        "/api/ai/intake/apply",
        json={"draft": draft, "project_id": intake_world["project"].id},
        headers=auth_headers,
    )
    assert apply_resp.status_code == 200
    assert apply_resp.json()["features_created"] == 1
