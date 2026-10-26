"""Tests for the copilot chat + proposal endpoints — grounded, human-confirmed writes.

The LLM is mocked: no live calls in CI. Chat assembles context via
build_context (RBAC-filtered), calls _call_llm, persists an AiInteraction,
and returns answer + sources. Proposals execute nothing until confirmed, and
confirmation enforces the user's authority over each target record.
"""
import json

import pytest

import app.models  # noqa: F401
from app.models.ai_interaction import AiInteraction
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.services import copilot as copilot_service


@pytest.fixture()
def copilot_world(db):
    """Tenant + super-admin user (plan gate passes) + project + item."""
    from app.models.tenant import TenantMembership

    tenant = Tenant(name="Chat Co", slug="chat-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    # The shared auth_headers fixture creates test@pmo.test (super_admin) —
    # give it an active tenant + membership so get_current_tenant resolves.
    admin = db.query(User).filter(User.email == "test@pmo.test").first()
    if not admin:
        admin = User(email="test@pmo.test", name="Admin", hashed_password="x", system_role="super_admin")
        db.add(admin)
        db.commit()
    admin.active_tenant_id = tenant.id
    db.add(TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="owner"))
    db.commit()
    db.refresh(admin)

    project = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=admin.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    item = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="SSO login",
        epic="Auth", current_phase="Development", status="In Progress",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"tenant": tenant, "admin": admin, "project": project, "item": item}


@pytest.fixture()
def ai_configured(monkeypatch):
    """Mock the per-tenant AI config and _call_llm (no live calls)."""
    from app.services import settings_service

    monkeypatch.setattr(settings_service, "get_ai_config", lambda db, tid: {"api_key": "k", "base_url": "u", "model": "m"})


def test_chat_requires_auth(client, copilot_world):
    resp = client.post("/api/ai/copilot/chat", json={"question": "what's overdue?"})
    assert resp.status_code in (401, 403)


def test_chat_unconfigured_returns_400(client, auth_headers, copilot_world, monkeypatch):
    """Tenant without an AI key → 400 with a helpful message.

    get_ai_config is imported into app.routers.ai's namespace, so patch there.
    """
    import app.routers.ai as ai_router

    monkeypatch.setattr(ai_router, "get_ai_config", lambda db, tid: {"api_key": "", "base_url": "", "model": ""})
    resp = client.post(
        "/api/ai/copilot/chat",
        json={"question": "what's overdue?"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "API key" in resp.json()["detail"]


def test_chat_returns_grounded_answer(client, auth_headers, copilot_world, ai_configured, monkeypatch):
    """Happy path: answer + sources, grounded via build_context, LLM mocked."""
    seen_prompts = {}

    def fake_call_llm(system_prompt, user_prompt, tenant_config=None, max_tokens=900):
        seen_prompts["system"] = system_prompt
        seen_prompts["user"] = user_prompt
        return json.dumps({"answer": "Nothing is overdue right now.", "sources": []})

    monkeypatch.setattr(copilot_service, "_call_llm", fake_call_llm)

    resp = client.post(
        "/api/ai/copilot/chat",
        json={"question": "what's overdue?"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "Nothing is overdue right now."
    assert "sources" in body
    assert "Answer only from the provided project data" in seen_prompts["system"]
    assert "PNU Cloud" in seen_prompts["user"]  # grounded in real context


def test_chat_persists_interaction(client, auth_headers, copilot_world, ai_configured, monkeypatch, db):
    """Every chat logs an AiInteraction kind=query."""
    monkeypatch.setattr(copilot_service, "_call_llm", lambda *a, **k: json.dumps({"answer": "ok", "sources": []}))

    resp = client.post("/api/ai/copilot/chat", json={"question": "status?"}, headers=auth_headers)
    assert resp.status_code == 200
    row = db.query(AiInteraction).filter(AiInteraction.kind == "query").first()
    assert row is not None
    assert row.question == "status?"


def test_propose_executes_nothing(client, auth_headers, copilot_world, ai_configured, monkeypatch, db):
    """Propose drafts an AiInteraction but writes no backlog changes."""
    monkeypatch.setattr(copilot_service, "_call_llm", lambda *a, **k: json.dumps(
        {"operations": [{"op": "advance_item", "item_id": copilot_world["item"].id, "target_phase": "Testing"}]},
    ))

    resp = client.post(
        "/api/ai/copilot/propose",
        json={"intent": "move SSO login to Testing"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"

    item = db.query(BacklogItem).filter(BacklogItem.id == copilot_world["item"].id).first()
    assert item.current_phase == "Development"  # untouched until confirm

    row = db.query(AiInteraction).filter(AiInteraction.kind == "proposal").first()
    assert row is not None and row.status == "pending"


def test_confirm_executes_proposal_as_user(client, auth_headers, copilot_world, ai_configured, monkeypatch, db):
    """Confirm executes the ops with the user's authority."""
    monkeypatch.setattr(copilot_service, "_call_llm", lambda *a, **k: json.dumps(
        {"operations": [{"op": "advance_item", "item_id": copilot_world["item"].id, "target_phase": "Testing"}]},
    ))
    propose = client.post("/api/ai/copilot/propose", json={"intent": "move SSO to Testing"}, headers=auth_headers)
    proposal_id = propose.json()["proposal_id"]

    resp = client.post(f"/api/ai/copilot/proposals/{proposal_id}/confirm", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["executed"], "the advance_item op should have executed"

    item = db.query(BacklogItem).filter(BacklogItem.id == copilot_world["item"].id).first()
    assert item.current_phase == "Testing"


def test_reject_discards_proposal(client, auth_headers, copilot_world, ai_configured, monkeypatch, db):
    monkeypatch.setattr(copilot_service, "_call_llm", lambda *a, **k: json.dumps(
        {"operations": [{"op": "advance_item", "item_id": copilot_world["item"].id, "target_phase": "Testing"}]},
    ))
    propose = client.post("/api/ai/copilot/propose", json={"intent": "move SSO to Testing"}, headers=auth_headers)
    proposal_id = propose.json()["proposal_id"]

    resp = client.post(f"/api/ai/copilot/proposals/{proposal_id}/reject", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    item = db.query(BacklogItem).filter(BacklogItem.id == copilot_world["item"].id).first()
    assert item.current_phase == "Development"  # never executed


def test_confirm_twice_returns_409(client, auth_headers, copilot_world, ai_configured, monkeypatch):
    monkeypatch.setattr(copilot_service, "_call_llm", lambda *a, **k: json.dumps({"operations": []}))
    propose = client.post("/api/ai/copilot/propose", json={"intent": "noop"}, headers=auth_headers)
    proposal_id = propose.json()["proposal_id"]

    client.post(f"/api/ai/copilot/proposals/{proposal_id}/confirm", headers=auth_headers)
    resp = client.post(f"/api/ai/copilot/proposals/{proposal_id}/confirm", headers=auth_headers)
    assert resp.status_code == 409


def test_unknown_ops_are_dropped(client, auth_headers, copilot_world, ai_configured, monkeypatch):
    """Vocabulary enforcement: ops outside PROPOSAL_OPS never get drafted."""
    monkeypatch.setattr(copilot_service, "_call_llm", lambda *a, **k: json.dumps(
        {"operations": [{"op": "delete_project", "project_id": 1}]},
    ))
    resp = client.post("/api/ai/copilot/propose", json={"intent": "nuke everything"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["operations"] == []  # dropped
