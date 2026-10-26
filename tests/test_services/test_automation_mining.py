"""Tests for self-proposing automation (P4.2).

mine_rules(db, tenant) scans ActivityLog + approvals + tasks for repeated
patterns and proposes AutomationRule rows (source=mined) with evidence —
never duplicates an existing rule with the same trigger, and never
auto-enables. coverage_scan reports what cold-start templates would apply.
"""
import json
from datetime import date, timedelta

from app.models.approval import ApprovalRequest
from app.models.automation_rule import AutomationRule
from app.models.project import Project
from app.models.user import User
from app.services.automation_mining import coverage_scan, mine_rules


def _world(db):
    from app.models.tenant import Tenant

    tenant = Tenant(name="Mine Tenant", slug="mine-tenant", plan="enterprise", status="active")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    user = User(
        email="miner@pmo.test", name="Miner",
        hashed_password="x", system_role="tenant_admin", active_tenant_id=tenant.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    project = Project(name="Mine Project", client_id=1, tenant_id=tenant.id, status="Active")
    db.add(project)
    db.commit()
    db.refresh(project)
    return tenant, user, project


def test_mining_proposes_aging_rule_from_evidence(db, auth_user):
    """3+ gates pending > 48h → propose an approval_aging rule with evidence."""
    tenant, user, project = _world(db)
    for i in range(3):
        a = ApprovalRequest(
            tenant_id=tenant.id, project_id=project.id,
            title=f"Gate {i}", request_type="release", status="Pending",
            requested_by=user.id,
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        a.created_at = (date.today() - timedelta(days=3)).isoformat()
        db.commit()

    proposals = mine_rules(db, tenant)
    aging = [p for p in proposals if p.trigger == "approval_aging"]
    assert len(aging) == 1
    assert aging[0].source == "mined"
    assert aging[0].enabled is False  # never auto-enabled
    assert aging[0].evidence["matches"] == 3
    assert "Gate 0" in json.dumps(aging[0].evidence["sample"])

    # Persisted as a real row
    rows = db.query(AutomationRule).filter(
        AutomationRule.tenant_id == tenant.id, AutomationRule.source == "mined",
    ).all()
    assert len(rows) == 1


def test_mining_never_duplicates_existing_trigger(db, auth_user):
    """An existing rule with the same trigger → no duplicate proposal."""
    tenant, user, project = _world(db)
    for i in range(3):
        a = ApprovalRequest(
            tenant_id=tenant.id, project_id=project.id,
            title=f"Gate {i}", request_type="release", status="Pending",
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        a.created_at = (date.today() - timedelta(days=3)).isoformat()
        db.commit()
    rule = AutomationRule(
        tenant_id=tenant.id, name="Already have one", trigger="approval_aging",
        conditions={"hours_in_gate": 48}, actions=[{"type": "notify", "role": "gate_owner"}],
        source="template", enabled=False,
    )
    db.add(rule)
    db.commit()

    proposals = mine_rules(db, tenant)
    assert all(p.trigger != "approval_aging" for p in proposals)


def test_mining_below_threshold_proposes_nothing(db, auth_user):
    """1 old gate is noise, not a pattern — no proposal."""
    tenant, user, project = _world(db)
    a = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id,
        title="One gate", request_type="release", status="Pending",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    a.created_at = (date.today() - timedelta(days=5)).isoformat()
    db.commit()

    proposals = mine_rules(db, tenant)
    assert all(p.trigger != "approval_aging" for p in proposals)


def test_coverage_scan_reports_cold_start_gaps(db, auth_user):
    """Coverage scan: which cold-start triggers have no rule yet + what would match."""
    tenant, user, project = _world(db)
    a = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id,
        title="Aging gate", request_type="release", status="Pending",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    a.created_at = (date.today() - timedelta(days=3)).isoformat()
    db.commit()

    scan = coverage_scan(db, tenant)
    assert "approval_aging" in [t["trigger"] for t in scan["gaps"]]
    aging = next(t for t in scan["gaps"] if t["trigger"] == "approval_aging")
    assert aging["would_match"] >= 1
