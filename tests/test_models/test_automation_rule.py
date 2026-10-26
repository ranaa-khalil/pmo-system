"""Tests for the AutomationRule model (P4.1).

AutomationRule: tenant-scoped trigger/conditions/actions JSON rows proposed
by mining or cold-start templates, enabled only by a human.
"""
import json

from app.models.automation_rule import RULE_ACTIONS, RULE_TRIGGERS, AutomationRule


def test_automation_rule_roundtrip(db_session, auth_user):
    rule = AutomationRule(
        tenant_id=auth_user["tenant"].id,
        name="Gate reminder",
        description="Notify the gate owner when an approval ages past 48h",
        trigger="approval_aging",
        conditions={"hours_in_gate": 48},
        actions=[{"type": "notify", "role": "gate_owner"}],
        source="template",
        evidence={"matches_last_30d": 3},
        enabled=False,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    assert rule.id is not None
    assert rule.trigger == "approval_aging"
    assert rule.enabled is False  # never auto-enabled
    assert json.loads(json.dumps(rule.conditions))["hours_in_gate"] == 48
    assert rule.actions[0]["type"] == "notify"


def test_rule_vocabularies_exposed():
    """The engine and UI share one vocabulary for triggers/actions."""
    assert "approval_aging" in RULE_TRIGGERS
    assert "task_overdue" in RULE_TRIGGERS
    assert "item_sent_back" in RULE_TRIGGERS
    assert {"notify", "create_task"} <= set(RULE_ACTIONS)
