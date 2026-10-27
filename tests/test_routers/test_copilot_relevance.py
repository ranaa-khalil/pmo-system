"""Copilot relevance tests — portfolio identity + conversation history.

User feedback: "the conversation is not relevant to projects, features,
vision, ... everything." Root causes fixed:
  1. Without an open project, identity (client/description/vision) came from
     projects[0] only — now every assigned project gets an identity block.
  2. No conversation history — follow-ups lost context; now history is
     rendered into the prompt.
  3. The system prompt never asked for project/feature/vision grounding.
"""
import json

import pytest

import app.models  # noqa: F401
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.project_vision import ProjectVision
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services import copilot as copilot_service


@pytest.fixture()
def relevance_world(db):
    """Two projects with distinct visions + a vision row on each."""
    tenant = Tenant(name="Relevance Co", slug="relevance-co", plan="enterprise")
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

    pnu = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=admin.id, description="Student services platform")
    crm = Project(name="Strova CRM", client_id=1, tenant_id=tenant.id, project_manager_id=admin.id, description="Tour operator CRM")
    db.add_all([pnu, crm])
    db.commit()
    db.refresh(pnu)
    db.refresh(crm)

    db.add(ProjectVision(project_id=pnu.id, tenant_id=tenant.id, statement="One portal for every PNU student service by 2027"))
    db.add(ProjectVision(project_id=crm.id, tenant_id=tenant.id, statement="Every Strova tour booked in under 3 minutes"))
    feat = BacklogItem(tenant_id=tenant.id, project_id=crm.id, title="Tour calendar sync", epic="Scheduling", current_phase="Requirements", status="Draft")
    db.add(feat)
    db.commit()
    return {"tenant": tenant, "admin": admin, "pnu": pnu, "crm": crm, "feat": feat}


def _prompt_for(db, world, question, project_id=None, history=None):
    captured = {}

    def fake_call_llm(system_prompt, user_prompt, tenant_config=None, max_tokens=900):
        captured["user"] = user_prompt
        return json.dumps({"answer": "ok", "sources": []})

    original = copilot_service._call_llm
    copilot_service._call_llm = fake_call_llm
    try:
        copilot_service.copilot_chat(
            db, world["admin"], world["tenant"], question,
            {"api_key": "k", "base_url": "", "model": ""},
            project_id=project_id, history=history,
        )
    finally:
        copilot_service._call_llm = original
    return captured["user"]


def test_portfolio_mode_carries_every_project_story(db, relevance_world):
    """Without an open project the prompt includes BOTH projects' identity —
    name, description, vision — not just the first-assigned project."""
    prompt = _prompt_for(db, relevance_world, "what's the status?")
    assert "PNU Cloud" in prompt
    assert "Strova CRM" in prompt
    assert "Student services platform" in prompt  # pnu description
    assert "Tour operator CRM" in prompt  # crm description
    assert "Every Strova tour booked in under 3 minutes" in prompt  # crm vision


def test_scoped_mode_keeps_full_identity(db, relevance_world):
    """Scoped chat still carries THIS project's description + vision."""
    prompt = _prompt_for(db, relevance_world, "what's this about?", project_id=relevance_world["pnu"].id)
    assert "THIS PROJECT" in prompt
    assert "PNU Cloud" in prompt
    assert "One portal for every PNU student service by 2027" in prompt


def test_conversation_history_rendered(db, relevance_world):
    """Follow-ups carry the recent conversation into the prompt."""
    history = [
        {"role": "user", "text": "The tour calendar sync is finished"},
        {"role": "assistant", "text": "Noted — Tour calendar sync done."},
    ]
    prompt = _prompt_for(db, relevance_world, "what should I do next?", history=history)
    assert "RECENT CONVERSATION" in prompt
    assert "The tour calendar sync is finished" in prompt


def test_system_prompt_demands_project_feature_vision_grounding():
    """The prompt instructs the model to name projects/features/visions and
    treat statements of work as status updates."""
    sp = copilot_service.CHAT_SYSTEM_PROMPT
    assert "Ground every answer in the specifics" in sp
    assert "vision" in sp.lower()
    assert "status updates" in sp
