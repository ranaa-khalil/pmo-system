"""Tests for the weekly brief service — audience-differentiated reporting.

generate_report assembles the SAME grounded data for every audience; the
shape varies by profile (exec verdict / PM operational / approver gate-only /
team task-only). Numbers never differ — only relevance filtering.
The send path is approval-gated: nothing is emailed without a digest
preference, and every report is persisted as an AiInteraction kind=report.
"""
import json

import pytest

import app.models  # noqa: F401
from app.models.ai_interaction import AiInteraction
from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services import brief


@pytest.fixture()
def brief_world(db):
    tenant = Tenant(name="Brief Co", slug="brief-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    pm = User(email="pm-brief@copilot.test", name="PM", hashed_password="x")
    db.add(pm)
    db.commit()
    db.refresh(pm)

    approver = User(email="tl-brief@copilot.test", name="Tech Lead", hashed_password="x")
    db.add(approver)
    db.commit()

    project = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    db.add(BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="SSO login",
        epic="Auth", current_phase="Development", status="In Progress",
    ))
    db.add(ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id, title="Release v1.1.0 sign-off",
        request_type="release", status="Pending",
    ))
    db.commit()
    return {"tenant": tenant, "pm": pm, "approver": approver, "project": project}


def test_generate_report_exec_weekly(db, brief_world, monkeypatch):
    """Exec shape: verdict up front, what changed, risks, decisions needed."""
    monkeypatch.setattr(brief, "_call_llm", lambda *a, **k: json.dumps({
        "verdict": "on track",
        "what_changed": ["SSO login progressed in Development"],
        "risks": ["Release v1.1.0 awaiting sign-off"],
        "decisions_needed": [],
    }))
    report = brief.generate_report(
        db, brief_world["tenant"], brief_world["project"],
        audience="exec_weekly",
    )
    assert report["audience"] == "exec_weekly"
    assert "verdict" in report["content"]
    assert report["content"]["verdict"] == "on track"
    assert report["data_hash"]  # same-grounding fingerprint
    row = db.query(AiInteraction).filter(AiInteraction.kind == "report").first()
    assert row is not None


def test_generate_report_pm_weekly(db, brief_world, monkeypatch):
    """PM shape: operational — gates pending, aging, overdue, escalation needs."""
    monkeypatch.setattr(brief, "_call_llm", lambda *a, **k: json.dumps({
        "gates_pending": ["Release v1.1.0 sign-off"],
        "aging_items": ["SSO login — Development for 7+ days"],
        "overdue_tasks": [],
        "needs_escalation": [],
    }))
    report = brief.generate_report(
        db, brief_world["tenant"], brief_world["project"],
        audience="pm_weekly", user=brief_world["pm"],
    )
    assert report["audience"] == "pm_weekly"
    assert "gates_pending" in report["content"]


def test_same_data_every_audience(db, brief_world, monkeypatch):
    """The grounding fingerprint is identical across audiences — same truth."""
    monkeypatch.setattr(brief, "_call_llm", lambda *a, **k: json.dumps({"ok": True}))
    r1 = brief.generate_report(db, brief_world["tenant"], brief_world["project"], audience="exec_weekly")
    r2 = brief.generate_report(db, brief_world["tenant"], brief_world["project"], audience="pm_weekly", user=brief_world["pm"])
    assert r1["data_hash"] == r2["data_hash"]


def test_generate_report_gate_digest(db, brief_world, monkeypatch):
    """Approver shape: what's waiting on me + evidence summary. Nothing else."""
    monkeypatch.setattr(brief, "_call_llm", lambda *a, **k: json.dumps({
        "waiting_on_me": ["Release v1.1.0 sign-off"],
        "evidence_summary": "3 features in scope, tests green",
        "changed_since_last": [],
    }))
    report = brief.generate_report(
        db, brief_world["tenant"], brief_world["project"],
        audience="approver_gate", user=brief_world["approver"],
    )
    assert report["audience"] == "approver_gate"
    assert "waiting_on_me" in report["content"]


def test_report_formats(db, brief_world, monkeypatch):
    """Every report renders to markdown + docx-ready sections."""
    monkeypatch.setattr(brief, "_call_llm", lambda *a, **k: json.dumps({
        "verdict": "on track", "what_changed": [], "risks": [], "decisions_needed": [],
    }))
    report = brief.generate_report(db, brief_world["tenant"], brief_world["project"], audience="exec_weekly")
    assert report["markdown"]
    assert report["sections"]


def test_send_requires_digest_preference(db, brief_world, monkeypatch):
    """The send path is approval-gated: no preference → nothing sent."""
    monkeypatch.setattr(brief, "_call_llm", lambda *a, **k: json.dumps({"verdict": "on track"}))
    report = brief.generate_report(db, brief_world["tenant"], brief_world["project"], audience="exec_weekly")

    result = brief.send_report(db, brief_world["tenant"], report, recipient=brief_world["pm"])
    assert result["sent"] is False
    assert "digest" in result["reason"].lower()


def test_send_with_digest_preference_queues_email(db, brief_world, monkeypatch):
    """With a digest preference the report is queued via email_service (not sent live in tests)."""
    monkeypatch.setattr(brief, "_call_llm", lambda *a, **k: json.dumps({"verdict": "on track"}))
    report = brief.generate_report(db, brief_world["tenant"], brief_world["project"], audience="exec_weekly")

    sent_calls = {}
    monkeypatch.setattr(brief, "_queue_email", lambda **kwargs: sent_calls.update(kwargs) or {"queued": True})

    result = brief.send_report(
        db, brief_world["tenant"], report,
        recipient=brief_world["pm"], digest_preference=True,
    )
    assert result["sent"] is True
    assert sent_calls.get("subject")
    assert "PNU Cloud" in sent_calls.get("body", "") or "PNU Cloud" in sent_calls.get("html", "")
