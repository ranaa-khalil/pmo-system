"""Tests for the RAID register — risks extended with kind (Risk/Assumption/Issue/Dependency).

One register, four kinds: kind-specific statuses, kind-specific fields
(validation_plan / resolution / needed_by / external_owner), and the escalation
chain (assumption→risk, risk→issue, dependency→issue) with escalated_from_id
lineage. MCP gains a list_raid tool.
"""
import json

import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.models.user import User


@pytest.fixture()
def raid_world(client, db):
    """Logged-in PM with a project and one open risk."""
    tenant = Tenant(name="RAID API Co", slug="raid-api-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-raidapi@copilot.test", name="PM", hashed_password="x", system_role="project_manager")
    db.add(pm)
    db.commit()
    db.refresh(pm)
    pm.active_tenant_id = tenant.id
    db.commit()
    from app.models.tenant import TenantMembership
    db.add(TenantMembership(user_id=pm.id, tenant_id=tenant.id, role="owner"))
    project = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    risk = Risk(
        tenant_id=tenant.id, project_id=project.id,
        title="SSO integration slips", severity="High", probability="Medium",
        status="Open", owner_id=pm.id, source="manual",
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)

    from app.services.auth import create_access_token
    token = create_access_token(data={"sub": str(pm.id)})
    client.headers.update({"Authorization": f"Bearer {token}"})
    return {"tenant": tenant, "pm": pm, "project": project, "risk": risk}


def _rpc(client, method, params=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/api/mcp", json=body)


# ── Kind creation & validation ────────────────────────────────

def test_create_assumption_with_validation_plan(raid_world, client):
    project = raid_world["project"]
    resp = client.post(f"/api/projects/{project.id}/risks", json={
        "title": "PNU API allows 1000 rpm", "kind": "Assumption",
        "validation_plan": "Load test the staging endpoint before Design sign-off",
    })
    assert resp.status_code == 200
    row = resp.json()
    assert row["kind"] == "Assumption"
    assert row["status"] == "Open"
    assert row["validation_plan"] == "Load test the staging endpoint before Design sign-off"


def test_create_dependency_with_external_owner(raid_world, client):
    project = raid_world["project"]
    resp = client.post(f"/api/projects/{project.id}/risks", json={
        "title": "OAuth module from CloudGate", "kind": "Dependency",
        "external_owner": "CloudGate team", "needed_by": "2026-12-01",
    })
    assert resp.status_code == 200
    row = resp.json()
    assert row["kind"] == "Dependency"
    assert row["external_owner"] == "CloudGate team"
    assert str(row["needed_by"]).startswith("2026-12-01")


def test_create_with_invalid_kind_422(raid_world, client):
    project = raid_world["project"]
    resp = client.post(f"/api/projects/{project.id}/risks", json={
        "title": "x", "kind": "Whatever",
    })
    assert resp.status_code == 422


def test_default_kind_is_risk(raid_world, client):
    project = raid_world["project"]
    resp = client.post(f"/api/projects/{project.id}/risks", json={"title": "No kind given"})
    row = resp.json()
    assert row["kind"] == "Risk"


# ── Kind filter ───────────────────────────────────────────────

def test_list_kind_filter(raid_world, client):
    project = raid_world["project"]
    client.post(f"/api/projects/{project.id}/risks", json={"title": "Assumption A", "kind": "Assumption"})
    client.post(f"/api/projects/{project.id}/risks", json={"title": "Issue A", "kind": "Issue"})
    rows = client.get(f"/api/projects/{project.id}/risks").json()
    assert {r["kind"] for r in rows} >= {"Risk", "Assumption", "Issue"}
    only_a = client.get(f"/api/projects/{project.id}/risks", params={"kind": "Assumption"}).json()
    assert only_a and all(r["kind"] == "Assumption" for r in only_a)
    assert any(r["title"] == "Assumption A" for r in only_a)


# ── Kind-specific status validation ──────────────────────────

def test_assumption_status_validated_ok(raid_world, client):
    project = raid_world["project"]
    a = client.post(f"/api/projects/{project.id}/risks", json={"title": "A", "kind": "Assumption"}).json()
    resp = client.put(f"/api/risks/{a['id']}", json={"status": "Validated"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "Validated"


def test_assumption_rejects_risk_status(raid_world, client):
    project = raid_world["project"]
    a = client.post(f"/api/projects/{project.id}/risks", json={"title": "A", "kind": "Assumption"}).json()
    resp = client.put(f"/api/risks/{a['id']}", json={"status": "Mitigating"})
    assert resp.status_code == 422


def test_issue_status_progression(raid_world, client):
    project = raid_world["project"]
    i = client.post(f"/api/projects/{project.id}/risks", json={"title": "Outage", "kind": "Issue"}).json()
    resp = client.put(f"/api/risks/{i['id']}", json={"status": "Resolved", "resolution": "Rolled back at 14:05"})
    assert resp.status_code == 200
    assert resp.json()["resolution"] == "Rolled back at 14:05"


# ── Escalation chain ─────────────────────────────────────────

def test_escalate_assumption_to_risk(raid_world, client):
    project = raid_world["project"]
    a = client.post(f"/api/projects/{project.id}/risks", json={
        "title": "PNU API 1000 rpm", "kind": "Assumption",
    }).json()
    resp = client.post(f"/api/risks/{a['id']}/escalate")
    assert resp.status_code == 200
    new = resp.json()
    assert new["kind"] == "Risk"
    assert new["escalated_from_id"] == a["id"]
    assert new["source"] == "escalation"
    # The source assumption is invalidated
    rows = client.get(f"/api/projects/{project.id}/risks").json()
    src = next(r for r in rows if r["id"] == a["id"])
    assert src["status"] == "Invalidated"


def test_escalate_risk_to_issue(raid_world, client):
    project = raid_world["project"]
    r = client.post(f"/api/projects/{project.id}/risks", json={
        "title": "SSO slips", "kind": "Risk", "severity": "High",
    }).json()
    resp = client.post(f"/api/risks/{r['id']}/escalate")
    assert resp.status_code == 200
    new = resp.json()
    assert new["kind"] == "Issue"
    assert new["escalated_from_id"] == r["id"]
    # The materialized risk closes
    rows = client.get(f"/api/projects/{project.id}/risks").json()
    src = next(x for x in rows if x["id"] == r["id"])
    assert src["status"] == "Closed"


def test_escalate_dependency_to_issue(raid_world, client):
    project = raid_world["project"]
    d = client.post(f"/api/projects/{project.id}/risks", json={
        "title": "OAuth module delivery", "kind": "Dependency",
    }).json()
    resp = client.post(f"/api/risks/{d['id']}/escalate")
    assert resp.status_code == 200
    new = resp.json()
    assert new["kind"] == "Issue"
    assert "OAuth module" in new["title"]
    # The dependency flips to Blocked
    rows = client.get(f"/api/projects/{project.id}/risks").json()
    src = next(x for x in rows if x["id"] == d["id"])
    assert src["status"] == "Blocked"


def test_escalate_issue_is_terminal_422(raid_world, client):
    project = raid_world["project"]
    i = client.post(f"/api/projects/{project.id}/risks", json={"title": "Outage", "kind": "Issue"}).json()
    resp = client.post(f"/api/risks/{i['id']}/escalate")
    assert resp.status_code == 422


def test_escalate_requires_pm(raid_world, client, db):
    project = raid_world["project"]
    # A non-PM tenant member cannot escalate
    from app.models.tenant import TenantMembership
    member = User(email="member-raid@copilot.test", name="Member", hashed_password="x")
    db.add(member)
    db.commit()
    db.refresh(member)
    db.add(TenantMembership(user_id=member.id, tenant_id=raid_world["tenant"].id, role="member"))
    db.commit()
    from app.services.auth import create_access_token
    client.headers.update({"Authorization": f"Bearer {create_access_token(data={'sub': str(member.id)})}"})
    resp = client.post(f"/api/risks/{raid_world['risk'].id}/escalate")
    assert resp.status_code == 403


# ── MCP list_raid tool ───────────────────────────────────────

def test_mcp_lists_list_raid_tool(raid_world, client):
    _rpc(client, "initialize", {})
    tools = _rpc(client, "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "list_raid" in names


def test_mcp_list_raid_returns_rows(raid_world, client):
    project = raid_world["project"]
    client.post(f"/api/projects/{project.id}/risks", json={
        "title": "Assumption X", "kind": "Assumption",
    })
    _rpc(client, "initialize", {})
    result = _rpc(client, "tools/call", {"name": "list_raid", "arguments": {
        "project_id": project.id, "open_only": False,
    }}).json()["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    kinds = {row["kind"] for row in payload["items"]}
    assert "Risk" in kinds and "Assumption" in kinds
