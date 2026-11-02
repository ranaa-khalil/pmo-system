"""Test the Agent Library API — TDD.

NL rule generation (deterministic keyword mapping), manual rule CRUD,
never-auto-enabled invariant, tenant scoping.
"""


class TestNLGeneration:
    """POST /api/automation/generate: NL description → rule draft."""

    def test_approval_aging_with_hours(self, client):
        resp = client.post("/api/automation/generate", json={
            "description": "When an approval has been sitting in a gate for 72 hours, notify the Tech Lead",
        })
        assert resp.status_code == 200
        draft = resp.json()
        assert draft["trigger"] == "approval_aging"
        assert draft["conditions"]["hours_in_gate"] == 72
        assert draft["actions"][0]["type"] == "notify"
        assert draft["actions"][0]["role"] == "Tech Lead"
        assert draft["source"] == "manual"

    def test_approval_aging_default_48h(self, client):
        resp = client.post("/api/automation/generate", json={
            "description": "Notify when an approval is stuck in a gate",
        })
        assert resp.status_code == 200
        draft = resp.json()
        assert draft["trigger"] == "approval_aging"
        assert draft["conditions"]["hours_in_gate"] == 48

    def test_days_converted_to_hours(self, client):
        resp = client.post("/api/automation/generate", json={
            "description": "If a gate approval sits for 2 days, escalate with a task",
        })
        assert resp.status_code == 200
        draft = resp.json()
        assert draft["conditions"]["hours_in_gate"] == 48
        assert any(a["type"] == "create_task" for a in draft["actions"])

    def test_task_overdue(self, client):
        resp = client.post("/api/automation/generate", json={
            "description": "When a task goes past its due date, notify the PM",
        })
        assert resp.status_code == 200
        assert resp.json()["trigger"] == "task_overdue"

    def test_item_blocked(self, client):
        resp = client.post("/api/automation/generate", json={
            "description": "When an item enters Blocked, flag it in the briefing",
        })
        assert resp.status_code == 200
        draft = resp.json()
        assert draft["trigger"] == "item_blocked"
        assert any(a["type"] == "flag" for a in draft["actions"])

    def test_kpi_off_target(self, client):
        resp = client.post("/api/automation/generate", json={
            "description": "When a KPI drifts off target, notify",
        })
        assert resp.status_code == 200
        assert resp.json()["trigger"] == "kpi_off_target"

    def test_default_action_is_notify(self, client):
        resp = client.post("/api/automation/generate", json={
            "description": "When a release advances a phase",
        })
        assert resp.status_code == 200
        draft = resp.json()
        assert draft["trigger"] == "release_advanced"
        assert draft["actions"] == [{"type": "notify"}]

    def test_unmappable_rejected_422(self, client):
        resp = client.post("/api/automation/generate", json={
            "description": "Make coffee automatically every morning",
        })
        assert resp.status_code == 422
        assert "trigger" in resp.json()["detail"].lower()

    def test_empty_rejected(self, client):
        resp = client.post("/api/automation/generate", json={"description": "   "})
        assert resp.status_code == 400


class TestRuleCRUD:
    """Manual agent CRUD: create, update, delete, tenant scoping."""

    def test_create_rule_201(self, client):
        resp = client.post("/api/automation/rules", json={
            "name": "Blocked escalation",
            "trigger": "item_blocked",
            "actions": [{"type": "notify", "role": "Product Owner"}],
        })
        assert resp.status_code == 201
        rule = resp.json()
        assert rule["trigger"] == "item_blocked"
        assert rule["enabled"] is False  # never auto-enabled
        assert rule["source"] == "manual"

    def test_create_with_explicit_enable(self, client):
        resp = client.post("/api/automation/rules", json={
            "name": "Overdue alert",
            "trigger": "task_overdue",
            "actions": [{"type": "notify"}],
            "enabled": True,  # a human explicitly requested it
        })
        assert resp.status_code == 201
        assert resp.json()["enabled"] is True

    def test_invalid_trigger_400(self, client):
        resp = client.post("/api/automation/rules", json={
            "name": "Bad trigger",
            "trigger": "coffee_ready",
            "actions": [{"type": "notify"}],
        })
        assert resp.status_code == 400

    def test_invalid_action_400(self, client):
        resp = client.post("/api/automation/rules", json={
            "name": "Bad action",
            "trigger": "item_blocked",
            "actions": [{"type": "deploy"}],
        })
        assert resp.status_code == 400

    def test_no_actions_400(self, client):
        resp = client.post("/api/automation/rules", json={
            "name": "No actions",
            "trigger": "item_blocked",
            "actions": [],
        })
        assert resp.status_code == 400

    def test_update_rule(self, client):
        rule = client.post("/api/automation/rules", json={
            "name": "Aging gate",
            "trigger": "approval_aging",
            "actions": [{"type": "notify"}],
        }).json()
        resp = client.put(f"/api/automation/rules/{rule['id']}", json={
            "enabled": True,
            "name": "Aging gate (48h)",
        })
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["enabled"] is True
        assert updated["name"] == "Aging gate (48h)"

    def test_delete_rule(self, client):
        rule = client.post("/api/automation/rules", json={
            "name": "Temporary",
            "trigger": "item_sent_back",
            "actions": [{"type": "notify"}],
        }).json()
        resp = client.delete(f"/api/automation/rules/{rule['id']}")
        assert resp.status_code == 200
        rules = client.get("/api/automation/rules").json()
        assert all(r["id"] != rule["id"] for r in rules)

    def test_list_rules_tenant_scoped(self, client):
        client.post("/api/automation/rules", json={
            "name": "Mine",
            "trigger": "item_blocked",
            "actions": [{"type": "notify"}],
        })
        rules = client.get("/api/automation/rules").json()
        assert all("name" in r and "trigger" in r for r in rules)

    def test_update_missing_404(self, client):
        resp = client.put("/api/automation/rules/99999", json={"enabled": True})
        assert resp.status_code == 404
