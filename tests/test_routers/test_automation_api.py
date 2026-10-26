"""API tests for self-proposing automation (P4.2).

GET /api/ai/automation/rules — list rules (tenant-scoped)
POST /api/ai/automation/scan — mine patterns + coverage scan
POST /api/ai/automation/rules/{id}/enable — human one-click enable
DELETE /api/ai/automation/rules/{id} — remove a rule
"""
from app.models.automation_rule import AutomationRule


def _rule(db, tenant, trigger="approval_aging", enabled=False):
    rule = AutomationRule(
        tenant_id=tenant.id, name="Gate aging", trigger=trigger,
        conditions={"hours_in_gate": 48}, actions=[{"type": "notify", "role": "gate_owner"}],
        source="mined", enabled=enabled,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def test_rules_list_scoped_to_tenant(client, db, auth_user):
    _rule(db, auth_user["tenant"])
    resp = client.get("/api/ai/automation/rules")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["rules"]) == 1
    assert data["rules"][0]["trigger"] == "approval_aging"


def test_scan_returns_coverage_and_mines(client, db, auth_user):
    resp = client.post("/api/ai/automation/scan", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert "proposed" in data and "coverage" in data
    # Cold-start gaps always include all 3 triggers when no rules exist
    assert {g["trigger"] for g in data["coverage"]["gaps"]} == {"approval_aging", "task_overdue", "item_sent_back"}


def test_enable_flips_enabled(client, db, auth_user):
    rule = _rule(db, auth_user["tenant"], enabled=False)
    resp = client.post(f"/api/ai/automation/rules/{rule.id}/enable", json={})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    db.refresh(rule)
    assert rule.enabled is True


def test_delete_rule(client, db, auth_user):
    rule = _rule(db, auth_user["tenant"])
    resp = client.delete(f"/api/ai/automation/rules/{rule.id}")
    assert resp.status_code in (200, 204)


def test_other_tenant_rule_404(client, db, auth_user):
    from app.models.tenant import Tenant

    other = Tenant(name="Other", slug="other", plan="enterprise", status="active")
    db.add(other)
    db.commit()
    db.refresh(other)
    rule = _rule(db, other)
    resp = client.post(f"/api/ai/automation/rules/{rule.id}/enable", json={})
    assert resp.status_code == 404
