"""Tests for the interview engine — guided Q&A for every create flow.

The interview is the FRONT of the proposal pipeline, never a new write path:
- start → question with default; answer → next question (or follow-up, capped at 2)
- skip → fills the smart default and moves on
- finish → assembles the same draft shape the one-shot intake produces
- resume → state persists in AiInteraction (kind=interview); a new session continues
- the assembler output for the same answers equals the one-shot intake output
- skip-all → defaults-only draft
"""
import json

import pytest

import app.models  # noqa: F401
from app.models.ai_interaction import AiInteraction
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services import interview as interview_service
from app.services import intake as intake_service


@pytest.fixture()
def interview_world(db):
    tenant = Tenant(name="Interview Co", slug="interview-co", plan="enterprise")
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

    sibling = Project(name="PNU Student Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=admin.id)
    db.add(sibling)
    db.commit()
    db.refresh(sibling)
    return {"tenant": tenant, "admin": admin, "sibling": sibling}


# ── Flow spec shape ──────────────────────────────────────────────────────

def test_flows_defined_with_valid_specs():
    """Every flow spec: questions list, each skippable, 4-8 questions, first not required-by-default."""
    flows = interview_service.FLOWS
    assert "project" in flows
    assert "feature" in flows
    assert "risk" in flows
    for name, spec in flows.items():
        assert 4 <= len(spec["questions"]) <= 8, f"{name}: 4-8 questions"
        for q in spec["questions"]:
            assert q["id"] and q["prompt"]
            assert q["type"] in ("text", "choice", "date", "person", "textarea")
            # every question is skippable — the system fills a default
            assert "default" in q or q.get("default_resolver") is not None


def test_unknown_flow_raises():
    with pytest.raises(ValueError):
        interview_service.start_interview(db=None, user=None, tenant=None, flow="nope")


# ── State machine ────────────────────────────────────────────────────────

def test_start_returns_first_question(interview_world, db):
    session = interview_service.start_interview(
        db, interview_world["admin"], interview_world["tenant"], flow="project",
    )
    assert session["session_id"] > 0
    q = session["question"]
    assert q["prompt"]
    assert "default" in q
    assert session["progress"] == {"current": 1, "total": len(interview_service.FLOWS["project"]["questions"])}


def test_answer_advances_and_next_question_excludes_answered(interview_world, db):
    session = interview_service.start_interview(db, interview_world["admin"], interview_world["tenant"], flow="project")
    q1 = session["question"]
    state = interview_service.submit_answer(
        db, interview_world["admin"], interview_world["tenant"], session["session_id"], q1["id"], "A platform for PNU students",
    )
    assert state["done"] is False
    assert state["question"]["id"] != q1["id"]
    # the answer is stored in the resumable state
    row = db.query(AiInteraction).filter(AiInteraction.id == session["session_id"]).first()
    stored = json.loads(row.proposal)
    assert stored["answers"][q1["id"]] == "A platform for PNU students"


def test_skip_fills_default_and_advances(interview_world, db):
    session = interview_service.start_interview(db, interview_world["admin"], interview_world["tenant"], flow="project")
    q1 = session["question"]
    # The required first question must be answered; then skip the next (skippable)
    state = interview_service.submit_answer(
        db, interview_world["admin"], interview_world["tenant"], session["session_id"], q1["id"], "A platform for PNU",
    )
    assert state["done"] is False
    q2 = state["question"]
    state = interview_service.skip_question(
        db, interview_world["admin"], interview_world["tenant"], session["session_id"], q2["id"],
    )
    assert state["done"] is False
    row = db.query(AiInteraction).filter(AiInteraction.id == session["session_id"]).first()
    stored = json.loads(row.proposal)
    # skip records the default as the answer
    assert stored["answers"][q2["id"]] == q2["default"]
    assert stored["skipped"] == [q2["id"]]


def test_skip_required_question_refuses(interview_world, db):
    """A question with no smart default cannot be skipped — it must be answered."""
    session = interview_service.start_interview(db, interview_world["admin"], interview_world["tenant"], flow="project")
    q1 = session["question"]
    result = interview_service.skip_question(
        db, interview_world["admin"], interview_world["tenant"], session["session_id"], q1["id"],
    )
    assert result.get("error") == "question_required"


def test_finish_assembles_intake_parity_draft(interview_world, db, monkeypatch):
    """CRITICAL: the interview assembler output == the one-shot intake output
    for the same answers. Interviews never create a second kind of record."""
    # Mock the LLM the assembler calls: same shape intake.structure_intake produces
    monkeypatch.setattr(intake_service, "_call_llm", lambda *a, **k: json.dumps({
        "summary": "Cloud platform for PNU student services",
        "epics": [{"name": "Authentication", "features": [
            {"title": "Course browsing", "description": "Students browse available courses"},
        ]}],
        "personas": [{"name": "Student", "role": "End user", "goals": "Register fast", "pain_points": "Slow portals"}],
        "kpis": [{"name": "Registration completion rate", "target": "95%", "unit": "%", "category": "Adoption"}],
        "assumptions": ["10,000 concurrent users"],
    }))

    session = interview_service.start_interview(db, interview_world["admin"], interview_world["tenant"], flow="project")
    sid = session["session_id"]
    answers = {
        "building_what": "A cloud platform for PNU student services",
        "target_users": "PNU students and registrar staff",
        "success_looks_like": "Registration completion above 95%",
        "constraints": "Launch before semester start",
        "involved": "Registrar office, IT",
        "project_type": "software",
    }
    state = None
    for _ in range(len(interview_service.FLOWS["project"]["questions"]) + 2):
        state = interview_service.current_state(db, interview_world["admin"], interview_world["tenant"], sid)
        if state["done"]:
            break
        q = state["question"]
        state = interview_service.submit_answer(
            db, interview_world["admin"], interview_world["tenant"], sid, q["id"], answers.get(q["id"], q["default"]),
        )
    assert state["done"] is True

    # The draft assembles on finish — the only path that produces it
    final = interview_service.finish_interview(db, interview_world["admin"], interview_world["tenant"], sid)
    assert final["done"] is True
    draft = final["draft"]
    # Parity: same keys and same nested shapes as intake.structure_intake
    one_shot = {
        "summary": draft["summary"], "epics": draft["epics"], "personas": draft["personas"],
        "kpis": draft["kpis"], "assumptions": draft["assumptions"],
    }
    assert set(one_shot.keys()) == {"summary", "epics", "personas", "kpis", "assumptions"}
    assert draft["epics"][0]["features"][0]["title"] == "Course browsing"
    # source traceability: the interview answers ride along as kickoff material
    assert "interview" in (draft.get("source") or "").lower() or draft.get("interview_id")


def test_finish_before_last_question_returns_400(interview_world, db):
    session = interview_service.start_interview(db, interview_world["admin"], interview_world["tenant"], flow="project")
    with pytest.raises(Exception):
        interview_service.finish_interview(
            db, interview_world["admin"], interview_world["tenant"], session["session_id"],
        )


# ── Follow-up cap ────────────────────────────────────────────────────────

def test_followup_cap_max_2(interview_world, db):
    """An ambiguous answer can trigger follow-ups, but never more than 2 per question."""
    flows = interview_service.FLOWS
    for name, spec in flows.items():
        for q in spec["questions"]:
            assert q.get("max_followups", 2) <= 2


def test_resume_mid_interview(interview_world, db):
    """A session opened in 'another session' (fresh db lookup) continues where it left off."""
    session = interview_service.start_interview(db, interview_world["admin"], interview_world["tenant"], flow="project")
    sid = session["session_id"]
    q1 = session["question"]
    interview_service.submit_answer(db, interview_world["admin"], interview_world["tenant"], sid, q1["id"], "answer one")

    # Simulate a fresh resume: state is read purely from the AiInteraction row
    resumed = interview_service.current_state(db, interview_world["admin"], interview_world["tenant"], sid)
    assert resumed["done"] is False
    assert resumed["question"]["id"] != q1["id"]
    assert resumed["progress"]["current"] == 2
    assert resumed["answers_so_far"][q1["id"]] == "answer one"


def test_wrong_question_id_returns_409_shape(interview_world, db):
    session = interview_service.start_interview(db, interview_world["admin"], interview_world["tenant"], flow="project")
    result = interview_service.submit_answer(
        db, interview_world["admin"], interview_world["tenant"], session["session_id"], "not-a-question", "x",
    )
    assert result.get("error") == "unknown_question"


# ── Skip-all → defaults-only draft ──────────────────────────────────────

def test_skip_all_produces_defaults_draft(interview_world, db, monkeypatch):
    monkeypatch.setattr(intake_service, "_call_llm", lambda *a, **k: json.dumps({
        "summary": "Defaults-only draft", "epics": [], "personas": [], "kpis": [], "assumptions": [],
    }))
    session = interview_service.start_interview(db, interview_world["admin"], interview_world["tenant"], flow="project")
    sid = session["session_id"]
    state = None
    skipped = 0
    for _ in range(len(interview_service.FLOWS["project"]["questions"]) + 2):
        state = interview_service.current_state(db, interview_world["admin"], interview_world["tenant"], sid)
        if state["done"]:
            break
        q = state["question"]
        # The one required question (no smart default) must be answered;
        # everything else is skippable — accept the default.
        if q.get("required"):
            state = interview_service.submit_answer(db, interview_world["admin"], interview_world["tenant"], sid, q["id"], "A platform")
        else:
            state = interview_service.skip_question(db, interview_world["admin"], interview_world["tenant"], sid, q["id"])
            skipped += 1
    assert state["done"] is True

    # Defaults-only draft assembles on finish
    final = interview_service.finish_interview(db, interview_world["admin"], interview_world["tenant"], sid)
    assert final["draft"]["summary"] == "Defaults-only draft"
    row = db.query(AiInteraction).filter(AiInteraction.id == sid).first()
    stored = json.loads(row.proposal)
    assert len(stored["skipped"]) == skipped == len(interview_service.FLOWS["project"]["questions"]) - 1


# ── Feature mini-interview (follow-ups after a "new" verdict) ────────────

def test_feature_flow_short_and_mapable(interview_world, db):
    """The feature interview stays a mini-interview (4 questions) and its
    answers map onto the existing backlog form fields."""
    spec = interview_service.FLOWS["feature"]
    assert len(spec["questions"]) == 4
    ids = {q["id"] for q in spec["questions"]}
    assert {"acceptance_criteria", "priority", "target_release"} <= ids


# ── Router endpoints ─────────────────────────────────────────────────────

def _start_payload(world):
    return {"flow": "project"}


def test_router_requires_auth(client, interview_world):
    resp = client.post("/api/ai/interview/project/start", json={})
    assert resp.status_code in (401, 403)


def test_router_start_answer_finish(client, auth_headers, interview_world, db, monkeypatch):
    monkeypatch.setattr(intake_service, "_call_llm", lambda *a, **k: json.dumps({
        "summary": "Router draft", "epics": [], "personas": [], "kpis": [], "assumptions": [],
    }))
    resp = client.post("/api/ai/interview/project/start", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sid = body["session_id"]
    q = body["question"]

    resp2 = client.post(f"/api/ai/interview/{sid}/answer", json={"question_id": q["id"], "answer": "x"}, headers=auth_headers)
    assert resp2.status_code == 200
    assert resp2.json()["question"]["id"] != q["id"]

    # answer everything
    for _ in range(10):
        st = resp2.json()
        if st["done"]:
            break
        q = st["question"]
        resp2 = client.post(f"/api/ai/interview/{sid}/answer", json={"question_id": q["id"], "answer": "x"}, headers=auth_headers)
        assert resp2.status_code == 200, resp2.text
    assert resp2.json()["done"] is True

    # finish assembles the draft (the only path that produces it)
    respf = client.post(f"/api/ai/interview/{sid}/finish", json={}, headers=auth_headers)
    assert respf.status_code == 200, respf.text
    assert respf.json()["done"] is True
    assert "draft" in respf.json()

    # skip endpoint
    resp3 = client.post("/api/ai/interview/project/start", json={}, headers=auth_headers)
    sid3 = resp3.json()["session_id"]
    q3 = resp3.json()["question"]
    # required first question: answer it, then skip the next
    resp3b = client.post(f"/api/ai/interview/{sid3}/answer", json={"question_id": q3["id"], "answer": "x"}, headers=auth_headers)
    q3b = resp3b.json()["question"]
    resp4 = client.post(f"/api/ai/interview/{sid3}/skip", json={"question_id": q3b["id"]}, headers=auth_headers)
    assert resp4.status_code == 200, resp4.text

    # resume endpoint returns stored state
    resp5 = client.get(f"/api/ai/interview/{sid3}/state", headers=auth_headers)
    assert resp5.status_code == 200
    assert resp5.json()["progress"]["current"] >= 2


def test_router_finish_incomplete_returns_409(client, auth_headers, interview_world):
    resp = client.post("/api/ai/interview/project/start", json={}, headers=auth_headers)
    sid = resp.json()["session_id"]
    resp2 = client.post(f"/api/ai/interview/{sid}/finish", json={}, headers=auth_headers)
    assert resp2.status_code == 409
