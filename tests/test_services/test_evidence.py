"""Tests for gate evidence generation — AI-drafted evidence at every gate.

When an ApprovalRequest is created, the service drafts the evidence pack the
approver needs (release notes, open items, test evidence, template-specific
deliverables) using the project's lifecycle vocabulary. Drafts are persisted
as AiInteraction kind=evidence and attached to the approval. Human edits and
signs — the draft is a starting point, never the final record.
"""
import json

import pytest

import app.models  # noqa: F401
from app.models.ai_interaction import AiInteraction
from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services import evidence


@pytest.fixture()
def ev_world(db):
    tenant = Tenant(name="Evidence Co", slug="evidence-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    pm = User(email="pm-ev@copilot.test", name="PM", hashed_password="x")
    db.add(pm)
    db.commit()
    db.refresh(pm)

    project = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id, project_type="software")
    db.add(project)
    db.commit()
    db.refresh(project)

    release = Release(tenant_id=tenant.id, project_id=project.id, version="1.1.0", name="Auth release", status="Testing")
    db.add(release)
    db.commit()
    db.refresh(release)

    db.add(BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="SSO login",
        epic="Auth", current_phase="Testing", status="In Progress",
    ))
    db.commit()
    return {"tenant": tenant, "pm": pm, "project": project, "release": release}


def test_draft_evidence_software_gate(db, ev_world, monkeypatch):
    """Software gate: release notes + open items + test evidence draft."""
    monkeypatch.setattr(evidence, "_call_llm", lambda *a, **k: json.dumps({
        "release_notes": "SSO login completed for faculty and students",
        "open_items": ["SSO login — in Testing"],
        "test_evidence": "Unit + integration green",
    }))
    approval = ApprovalRequest(
        tenant_id=ev_world["tenant"].id, project_id=ev_world["project"].id,
        title="Release v1.1.0 UAT sign-off", request_type="release",
        target_phase="Ready for UAT", status="Pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    result = evidence.draft_evidence(db, ev_world["tenant"], ev_world["project"], approval)

    assert result["release_notes"].startswith("SSO login")
    row = db.query(AiInteraction).filter(AiInteraction.kind == "evidence").first()
    assert row is not None
    assert row.project_id == ev_world["project"].id


def test_draft_evidence_uses_template_deliverables(db, ev_world, monkeypatch):
    """The draft requests the template's gate deliverables for the target phase."""
    captured = {}

    def fake_llm(system, user, *a, **k):
        captured["user"] = user
        return json.dumps({"release_notes": "x", "open_items": [], "test_evidence": ""})

    monkeypatch.setattr(evidence, "_call_llm", fake_llm)
    approval = ApprovalRequest(
        tenant_id=ev_world["tenant"].id, project_id=ev_world["project"].id,
        title="Gate", request_type="phase", target_phase="Ready for UAT", status="Pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    evidence.draft_evidence(db, ev_world["tenant"], ev_world["project"], approval)
    # "Ready for UAT" gate deliverables from the software template are requested
    assert "Release notes draft" in captured["user"]
    assert "Rollback plan" in captured["user"]


def test_draft_evidence_ai_template(db, ev_world, monkeypatch):
    """AI project gate: dataset/bias/drift deliverables requested."""
    captured = {}
    monkeypatch.setattr(evidence, "_call_llm", lambda s, u, *a, **k: captured.update(user=u) or json.dumps({"notes": ""}))

    project = ev_world["project"]
    project.project_type = "ai"
    db.commit()

    approval = ApprovalRequest(
        tenant_id=ev_world["tenant"].id, project_id=project.id,
        title="Data gate", request_type="phase", target_phase="Evaluation", status="Pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    evidence.draft_evidence(db, ev_world["tenant"], project, approval)
    assert "Model performance report" in captured["user"]
    assert "Bias & fairness assessment" in captured["user"]


def test_draft_evidence_grounds_in_real_data(db, ev_world, monkeypatch):
    """The prompt includes the release's real backlog state (grounded)."""
    captured = {}
    monkeypatch.setattr(evidence, "_call_llm", lambda s, u, *a, **k: captured.update(user=u) or json.dumps({"notes": ""}))

    approval = ApprovalRequest(
        tenant_id=ev_world["tenant"].id, project_id=ev_world["project"].id,
        title="Gate", request_type="release", target_phase="Testing", status="Pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    evidence.draft_evidence(db, ev_world["tenant"], ev_world["project"], approval)
    assert "SSO login" in captured["user"]  # real item in the prompt
