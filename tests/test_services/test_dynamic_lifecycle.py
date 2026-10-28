"""Dynamic lifecycle + Artifact Chain wiring tests (R2 methodology).

- SDLC/ADLC/Hybrid built-in templates resolve with their own vocabularies.
- /advance reads the PROJECT's template dynamically (Implementation for SDLC,
  Agent Build for ADLC/Hybrid), not the hardcoded Software list.
- Gate decisions, AI evidence drafts, and template changes append hash-linked
  entries; the trail verifies intact.
"""
import app.models  # noqa: F401
from app.services.lifecycle import (  # noqa: I001 — one block, sorted
    GITHUB_SYNC_PHASES,
    gate_deliverables,
    item_phases,
    template_for,
)

# ── Built-in templates ──────────────────────────────────────────────────

def test_sdlc_template_vocabulary():
    assert "Implementation" in item_phases("sdlc")
    assert "Development" not in item_phases("sdlc")
    assert "SRS" in gate_deliverables("sdlc")["Requirements"]


def test_adlc_template_vocabulary():
    assert "Agent Build" in item_phases("adlc")
    assert "Agent Intent" in item_phases("adlc")
    delivs = gate_deliverables("adlc")
    assert any("Guardrail" in d for d in delivs["Tooling & Guardrails"])
    fields = template_for("adlc")["fields"]
    names = {f["name"] for f in fields}
    assert "agent_version" in names and "guardrail_status" in names


def test_hybrid_merges_both_tracks():
    phases = item_phases("hybrid")
    assert "Development" in phases and "Agent Build" in phases
    assert phases.index("Agent Build") > phases.index("Development")
    delivs = gate_deliverables("hybrid")
    assert any("Agent eval" in d for d in delivs["Testing"])


def test_github_sync_phases_per_template():
    assert GITHUB_SYNC_PHASES["sdlc"] == ["Implementation"]
    assert GITHUB_SYNC_PHASES["adlc"] == ["Agent Build"]
    assert "Development" in GITHUB_SYNC_PHASES["hybrid"]
    assert "Agent Build" in GITHUB_SYNC_PHASES["hybrid"]


def test_software_default_unchanged():
    assert item_phases("software")[0] == "Requirements"
    assert item_phases("unknown-type") == item_phases("software")


# ── Dynamic advance ─────────────────────────────────────────────────────

class TestDynamicAdvance:
    def _project(self, client, project_type):
        cid = client.post("/api/clients", json={"name": f"C {project_type}"}).json()["id"]
        return client.post("/api/projects", json={
            "name": f"P {project_type}", "client_id": cid, "project_type": project_type,
        }).json()["id"]

    def _item(self, client, pid, title="Dynamic item"):
        return client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid, "title": title,
        }).json()["id"]

    def test_sdlc_item_advances_through_implementation(self, client):
        pid = self._project(client, "sdlc")
        bid = self._item(client, pid)
        assert client.post(f"/api/backlog/{bid}/advance").json()["current_phase"] == "Design"
        resp = client.post(f"/api/backlog/{bid}/advance")
        assert resp.status_code == 200
        assert resp.json()["current_phase"] == "Implementation"

    def test_adlc_item_advances_through_agent_build(self, client):
        pid = self._project(client, "adlc")
        bid = self._item(client, pid)
        client.post(f"/api/backlog/{bid}/advance")  # → Tooling & Guardrails
        resp = client.post(f"/api/backlog/{bid}/advance")
        assert resp.status_code == 200
        assert resp.json()["current_phase"] == "Agent Build"

    def test_hybrid_item_walks_both_development_then_agent_build(self, client):
        pid = self._project(client, "hybrid")
        bid = self._item(client, pid)
        # Requirements → Design → Development → Agent Build → Testing
        for expected in ["Design", "Development", "Agent Build"]:
            resp = client.post(f"/api/backlog/{bid}/advance")
            assert resp.status_code == 200, resp.text
            assert resp.json()["current_phase"] == expected
        resp = client.post(f"/api/backlog/{bid}/advance")
        assert resp.status_code == 200
        assert resp.json()["current_phase"] == "Testing"

    def test_software_item_still_uses_development(self, client):
        pid = self._project(client, "software")
        bid = self._item(client, pid)
        resp = client.post(f"/api/backlog/{bid}/advance")  # → Design
        resp = client.post(f"/api/backlog/{bid}/advance")
        assert resp.json()["current_phase"] == "Development"


# ── Artifact Chain wiring ────────────────────────────────────────────────

class TestArtifactChainWiring:
    def _project(self, client):
        cid = client.post("/api/clients", json={"name": "Chain Wire"}).json()["id"]
        return client.post("/api/projects", json={"name": "Chain Wire P", "client_id": cid}).json()["id"]

    def test_gate_lifecycle_appends_hash_linked_entries(self, client):
        """Create → approve a gate: the approval's trail has created + approved
        entries, hash-linked, and verifies intact."""
        from app.services.artifact_chain import verify_chain

        pid = self._project(client)
        resp = client.post(f"/api/projects/{pid}/approvals", json={
            "project_id": pid,
            "title": "Gate: Requirements → Planning",
            "request_type": "release",
            "steps": [{"step_order": 1, "role_name": "Product Owner"}],
        })
        assert resp.status_code == 201
        approval_id = resp.json()["id"]

        steps = client.get(f"/api/approvals/{approval_id}").json()["steps"]
        step_id = steps[0]["id"]
        app_resp = client.post(f"/api/approvals/{approval_id}/steps/{step_id}/approve", json={})
        assert app_resp.status_code == 200

        # The project row is in the same tenant — verify via the service
        from tests.conftest import TestSessionLocal
        s = TestSessionLocal()
        verdict = verify_chain(s, 1, "approval_request", approval_id)
        s.close()
        assert verdict["valid"] is True
        assert verdict["length"] == 2  # created + approved

        trail = client.get(f"/api/artifacts/approval_request/{approval_id}")
        assert trail.status_code == 200
        body = trail.json()
        actions = [e["action"] for e in body["entries"]]
        assert actions == ["created", "approved"]
        assert body["valid"] is True
        assert body["entries"][1]["prev_hash"] == body["entries"][0]["hash"]

    def test_backlog_advance_appends_chain_entry(self, client):
        pid = self._project(client)
        bid = client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid, "title": "Chain item",
        }).json()["id"]
        client.post(f"/api/backlog/{bid}/advance")

        trail = client.get(f"/api/artifacts/backlog_item/{bid}")
        assert trail.status_code == 200
        body = trail.json()
        assert body["valid"] is True
        assert any(e["action"] == "advanced" and e["payload"].get("to_phase") == "Design"
                   for e in body["entries"])
