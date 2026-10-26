"""Tests for the rules engine worker (P4.1).

evaluate_rules(db, tenant) scans enabled AutomationRule rows, matches the
triggers against real data, executes the actions (notify / create_task),
and records fire_count / last_fired_at. Never invents data; never fires a
disabled rule; idempotent within a run.
"""
from datetime import date, timedelta

from app.models.approval import ApprovalRequest
from app.models.automation_rule import AutomationRule
from app.models.notification import Notification
from app.models.project import Project
from app.models.user import User
from app.models.user_task import UserTask
from app.services.rules_engine import evaluate_rules


def _world(db):
    """Tenant + user + project for engine tests."""
    from app.models.tenant import Tenant

    tenant = Tenant(name="Engine Tenant", slug="engine-tenant", plan="enterprise", status="active")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    user = User(
        email="engine@pmo.test", name="Engine User",
        hashed_password="x", system_role="tenant_admin", active_tenant_id=tenant.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    project = Project(name="Engine Project", client_id=1, tenant_id=tenant.id, status="Active")
    db.add(project)
    db.commit()
    db.refresh(project)
    return tenant, user, project


def test_approval_aging_rule_notifies_gate_owner(db, auth_user):
    tenant, user, project = _world(db)
    # An approval stuck pending for 3 days (72h) → matches hours_in_gate: 48
    approval = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id,
        title="Release 1.0.0: Requirements → Design",
        request_type="release", status="Pending",
        requested_by=user.id,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    # Backdate created_at by 3 days
    approval.created_at = (date.today() - timedelta(days=3)).isoformat()
    db.commit()

    rule = AutomationRule(
        tenant_id=tenant.id, name="Gate aging 48h",
        trigger="approval_aging", conditions={"hours_in_gate": 48},
        actions=[{"type": "notify", "role": "gate_owner"}],
        source="template", enabled=True,
    )
    db.add(rule)
    db.commit()

    result = evaluate_rules(db, tenant)
    assert result["evaluated"] == 1
    assert result["fired"] >= 1

    notes = db.query(Notification).filter(
        Notification.tenant_id == tenant.id, Notification.user_id == user.id,
    ).all()
    assert any("Release 1.0.0" in n.title for n in notes)
    db.refresh(rule)
    assert rule.fire_count >= 1
    assert rule.last_fired_at is not None


def test_disabled_rule_never_fires(db, auth_user):
    tenant, user, project = _world(db)
    approval = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id,
        title="Stuck approval", request_type="release", status="Pending",
    )
    db.add(approval)
    db.commit()
    approval.created_at = (date.today() - timedelta(days=5)).isoformat()
    db.commit()

    AutomationRule(
        tenant_id=tenant.id, name="Disabled", trigger="approval_aging",
        conditions={"hours_in_gate": 1}, actions=[{"type": "notify", "role": "gate_owner"}],
        source="template", enabled=False,
    )
    db.commit()

    result = evaluate_rules(db, tenant)
    assert result["evaluated"] == 0
    notes = db.query(Notification).filter(Notification.tenant_id == tenant.id).all()
    assert notes == []


def test_task_overdue_rule_creates_escalation_task(db, auth_user):
    tenant, user, project = _world(db)
    task = UserTask(
        tenant_id=tenant.id, title="Update test accounts",
        assigned_to=user.id, project_id=project.id,
        due_date=date.today() - timedelta(days=2),
        status="In Progress",
    )
    db.add(task)
    db.commit()

    rule = AutomationRule(
        tenant_id=tenant.id, name="Overdue escalation",
        trigger="task_overdue", conditions={"days_overdue": 1},
        actions=[{"type": "create_task", "title_prefix": "Escalate: "}],
        source="template", enabled=True,
    )
    db.add(rule)
    db.commit()

    evaluate_rules(db, tenant)
    escalations = db.query(UserTask).filter(
        UserTask.tenant_id == tenant.id, UserTask.title.like("Escalate:%"),
    ).all()
    assert len(escalations) == 1
    assert escalations[0].assigned_to == user.id


def test_fresh_approval_below_threshold_not_notified(db, auth_user):
    """Idempotence: a 1-hour-old approval does not match hours_in_gate: 48."""
    tenant, user, project = _world(db)
    approval = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id,
        title="Fresh gate", request_type="release", status="Pending",
    )
    db.add(approval)
    db.commit()  # created_at = now

    AutomationRule(
        tenant_id=tenant.id, name="Gate aging 48h", trigger="approval_aging",
        conditions={"hours_in_gate": 48}, actions=[{"type": "notify", "role": "gate_owner"}],
        source="template", enabled=True,
    )
    db.commit()

    result = evaluate_rules(db, tenant)
    notes = db.query(Notification).filter(Notification.tenant_id == tenant.id).all()
    assert notes == []
    assert result["fired"] == 0
