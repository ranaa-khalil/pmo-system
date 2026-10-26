"""Tests for the infrastructure API — environments, secrets (encrypted + versions), assets.

Secrets are encrypted at rest (never returned in plaintext by list), reveal
decrypts + logs access, rotate bumps the version, and everything is
tenant-scoped: another tenant's rows 404.
"""
import pytest

import app.models  # noqa: F401
from app.models.infrastructure import Environment, Secret
from app.models.project import Project


@pytest.fixture()
def infra_world(client, db, auth_user):
    """The shared owner + a project + one environment."""
    tenant = auth_user["tenant"]
    project = Project(name="Infra P", client_id=1, tenant_id=tenant.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    env = Environment(tenant_id=tenant.id, name="UAT", type="uat", status="active")
    db.add(env)
    db.commit()
    db.refresh(env)
    return {"tenant": tenant, "project": project, "env": env}


# ── Environments ─────────────────────────────────────────────────

def test_environment_crud(infra_world, client, db):
    project = infra_world["project"]
    resp = client.post(f"/api/projects/{project.id}/infra/environments", json={
        "name": "Production", "type": "production", "url": "https://app.example.com",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Production"
    eid = data["id"]

    rows = client.get(f"/api/projects/{project.id}/infra/environments").json()
    names = {e["name"] for e in rows}
    assert "Production" in names and "UAT" in names

    resp = client.put(f"/api/infra/environments/{eid}", json={"status": "maintenance"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "maintenance"

    resp = client.delete(f"/api/infra/environments/{eid}")
    assert resp.status_code == 200


# ── Secrets ──────────────────────────────────────────────────────

def test_secret_create_encrypted(infra_world, client, db):
    """The stored value is encrypted; the list never contains the plaintext."""
    project = infra_world["project"]
    env = infra_world["env"]
    resp = client.post(f"/api/projects/{project.id}/infra/secrets", json={
        "name": "DB password", "value": "SuperSecret99!", "environment_id": env.id,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "DB password"
    sid = data["id"]
    assert "SuperSecret99!" not in str(data)

    row = db.query(Secret).filter(Secret.id == sid).first()
    assert row.encrypted_value != "SuperSecret99!"
    assert "SuperSecret99!" not in row.encrypted_value


def test_secret_create_requires_value(infra_world, client):
    project = infra_world["project"]
    resp = client.post(f"/api/projects/{project.id}/infra/secrets", json={"name": "No value"})
    assert resp.status_code == 400


def test_secret_reveal_and_audit(infra_world, client, db):
    project = infra_world["project"]
    sid = client.post(f"/api/projects/{project.id}/infra/secrets", json={
        "name": "API key", "value": "RevealMe42!",
    }).json()["id"]

    resp = client.get(f"/api/infra/secrets/{sid}/reveal")
    assert resp.status_code == 200
    data = resp.json()
    assert data["value"] == "RevealMe42!"
    assert data["version"] == 1

    # Reveal is audit-logged
    from app.models.infrastructure import SecretAccessLog
    log = db.query(SecretAccessLog).filter(
        SecretAccessLog.secret_id == sid, SecretAccessLog.action == "reveal",
    ).first()
    assert log is not None


def test_secret_update_creates_version(infra_world, client, db):
    project = infra_world["project"]
    sid = client.post(f"/api/projects/{project.id}/infra/secrets", json={
        "name": "Rotating", "value": "v1-value",
    }).json()["id"]

    resp = client.put(f"/api/infra/secrets/{sid}", json={"value": "v2-value"})
    assert resp.status_code == 200
    assert resp.json()["version"] == 2

    versions = client.get(f"/api/infra/secrets/{sid}/versions").json()
    assert len(versions) == 2
    # No plaintext in version history
    assert "v1-value" not in str(versions) and "v2-value" not in str(versions)


def test_secret_rotate(infra_world, client, db):
    project = infra_world["project"]
    sid = client.post(f"/api/projects/{project.id}/infra/secrets", json={
        "name": "Rotate target", "value": "old-secret",
    }).json()["id"]

    resp = client.post(f"/api/infra/secrets/{sid}/rotate", json={"value": "new-secret"})
    assert resp.status_code == 200
    assert resp.json()["version"] == 2

    # Reveal returns the new value
    assert client.get(f"/api/infra/secrets/{sid}/reveal").json()["value"] == "new-secret"


def test_secret_rotate_requires_value(infra_world, client):
    project = infra_world["project"]
    sid = client.post(f"/api/projects/{project.id}/infra/secrets", json={
        "name": "Rotate empty", "value": "x",
    }).json()["id"]
    resp = client.post(f"/api/infra/secrets/{sid}/rotate", json={})
    assert resp.status_code == 400


def test_secret_delete(infra_world, client, db):
    project = infra_world["project"]
    sid = client.post(f"/api/projects/{project.id}/infra/secrets", json={
        "name": "Doomed", "value": "bye",
    }).json()["id"]
    resp = client.delete(f"/api/infra/secrets/{sid}")
    assert resp.status_code == 200
    assert db.query(Secret).filter(Secret.id == sid).first() is None


# ── Assets ───────────────────────────────────────────────────────

def test_asset_crud(infra_world, client, db):
    project = infra_world["project"]
    resp = client.post(f"/api/projects/{project.id}/infra/assets", json={
        "name": "api-gateway", "asset_type": "service", "cost_monthly": 120,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "api-gateway"
    aid = data["id"]

    rows = client.get(f"/api/projects/{project.id}/infra/assets").json()
    assert any(a["name"] == "api-gateway" for a in rows)

    resp = client.put(f"/api/infra/assets/{aid}", json={"status": "retired"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "retired"

    resp = client.delete(f"/api/infra/assets/{aid}")
    assert resp.status_code == 200


# ── Overview ─────────────────────────────────────────────────────

def test_infra_overview_counts(infra_world, client):
    project = infra_world["project"]
    client.post(f"/api/projects/{project.id}/infra/secrets", json={
        "name": "Overview secret", "value": "v",
    })
    resp = client.get(f"/api/projects/{project.id}/infra/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["counts"]["environments"] >= 1
    assert data["counts"]["secrets"] >= 1
    assert "assets_by_type" in data and "secrets_by_category" in data


# ── Tenant isolation ─────────────────────────────────────────────

def test_other_tenant_secret_404(infra_world, client, db):
    """Another tenant's secret cannot be revealed or rotated."""
    from app.models.tenant import Tenant
    from app.services.encryption import encrypt_value

    other = Tenant(name="Other Infra", slug="other-infra", plan="team")
    db.add(other)
    db.commit()
    db.refresh(other)
    other_secret = Secret(
        tenant_id=other.id, name="Theirs", category="custom",
        encrypted_value=encrypt_value("theirs"), version=1, status="active",
    )
    db.add(other_secret)
    db.commit()
    db.refresh(other_secret)

    assert client.get(f"/api/infra/secrets/{other_secret.id}/reveal").status_code == 404
    assert client.post(f"/api/infra/secrets/{other_secret.id}/rotate", json={"value": "x"}).status_code == 404
