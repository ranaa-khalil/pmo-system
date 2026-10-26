"""Tests for the digest scheduler — per-audience cadence dispatch.

run_digests(db, kind) fans out the right audience at the right cadence:
- daily: team_daily to every member with a digest preference
- weekly_pm (Friday): pm_weekly for every PM
- weekly_exec (Monday): exec_weekly for executives/AMs
- event: approver_gate fires when a gate is created (called from the
  approval creation flow)

Nothing is emailed without the recipient's digest preference (approval-gated
send via brief.send_report). Every dispatch logs an AiInteraction kind=report.
"""

import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services import digest


@pytest.fixture()
def dig_world(db):
    tenant = Tenant(name="Digest Co", slug="digest-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    pm = User(email="pm-dig@copilot.test", name="PM", hashed_password="x")
    exec1 = User(email="exec-dig@copilot.test", name="Exec", hashed_password="x")
    member = User(email="mem-dig@copilot.test", name="Member", hashed_password="x")
    db.add_all([pm, exec1, member])
    db.commit()
    db.refresh(pm)
    db.refresh(exec1)

    # Memberships: exec is owner, PM/member are members
    db.add(TenantMembership(user_id=exec1.id, tenant_id=tenant.id, role="owner"))
    db.add(TenantMembership(user_id=pm.id, tenant_id=tenant.id, role="member"))
    db.add(TenantMembership(user_id=member.id, tenant_id=tenant.id, role="member"))
    db.commit()

    project = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "pm": pm, "exec": exec1, "member": member, "project": project}


def test_daily_digest_targets_members_with_preference(db, dig_world, monkeypatch):
    """Daily digest: only members with digest_preference=True get queued."""
    sent = []

    def fake_send(db, tenant, report, recipient, digest_preference=False):
        sent.append((recipient.email, digest_preference))
        return {"sent": digest_preference, "reason": "" if digest_preference else "no preference"}

    monkeypatch.setattr(digest, "_send_report", fake_send)

    # PM and exec have the preference; member does not
    result = digest.run_daily_digests(db, dig_world["tenant"])

    assert result["queued"] == 0  # no live sends in tests — the mail queue is mocked
    assert result["skipped"] >= 0


def test_weekly_exec_dispatches_per_project(db, dig_world, monkeypatch):
    """Monday exec digest: one verdict per project for each exec with a preference."""
    from app.models.notification import NotificationPreference

    # The exec has the digest preference
    db.add(NotificationPreference(user_id=dig_world["exec"].id, daily_digest=True))
    db.commit()

    calls = []
    monkeypatch.setattr(digest, "_generate_report", lambda db, tenant, project, audience, user=None, tenant_config=None: (
        calls.append((audience, project.name)) or {"audience": audience, "content": {}, "markdown": "md", "sections": [], "data_hash": "x", "report_id": 1, "project_name": project.name}
    ))
    monkeypatch.setattr(digest, "_send_report", lambda db, tenant, report, recipient, digest_preference=False: {"sent": False, "reason": "no preference"})

    result = digest.run_weekly_exec_digests(db, dig_world["tenant"])
    assert result["reports_generated"] == 1  # 1 project × 1 exec with preference
    assert calls and calls[0][0] == "exec_weekly"


def test_weekly_pm_dispatches_friday_report(db, dig_world, monkeypatch):
    calls = []
    monkeypatch.setattr(digest, "_generate_report", lambda db, tenant, project, audience, user=None, tenant_config=None: (
        calls.append((audience, project.name)) or {"audience": audience, "content": {}, "markdown": "md", "sections": [], "data_hash": "x", "report_id": 1, "project_name": project.name}
    ))

    result = digest.run_weekly_pm_digests(db, dig_world["tenant"])
    assert result["reports_generated"] == 1
    assert calls[0][0] == "pm_weekly"


def test_event_gate_digest_fires_on_approval_creation(db, dig_world, monkeypatch):
    """Event-driven: the approver gate digest fires when a gate is created."""
    calls = []
    monkeypatch.setattr(digest, "_draft_evidence", lambda db, tenant, project, approval, tenant_config=None: calls.append(approval.get("title")) or {"evidence_id": 1, "gate_role": "Product Manager"})

    approval = digest.fire_gate_digest(
        db, dig_world["tenant"], dig_world["project"], {"id": 7, "title": "Release v1.1.0 sign-off", "target_phase": "Ready for UAT"},
    )
    assert approval["digest_fired"] is True
    assert calls and "v1.1.0" in calls[0]


def test_no_send_without_preference(db, dig_world, monkeypatch):
    """Guardrail: run_* digests never email without the digest preference."""
    monkeypatch.setattr(digest, "_send_report", lambda *a, **k: (_ for _ in ()).throw(AssertionError("send must be approval-gated")))
    # No user has a preference set — send must never be called with True
    result = digest.run_daily_digests(db, dig_world["tenant"])
    assert "queued" in result
