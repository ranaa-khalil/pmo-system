"""Tests for the API keys router — create, list, revoke per-tenant keys.

Owner/admin only: creating, listing, and revoking requires the owner or admin
tenant role. The full key is shown exactly once at creation; the list only
returns masked prefixes. Revocation is tenant-scoped — another tenant's key
404s.
"""
import pytest

import app.models  # noqa: F401
from app.models.api_key import ApiKey


@pytest.fixture()
def keys_world(client, db, auth_user):
    """The shared owner + one existing key."""
    tenant = auth_user["tenant"]
    user = auth_user["user"]
    raw = ApiKey.generate_key()
    key = ApiKey(
        tenant_id=tenant.id,
        name="CI key",
        key_hash=ApiKey.hash_key(raw),
        key_prefix=ApiKey.get_prefix(raw),
        scopes="read",
        created_by=user.id,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return {"tenant": tenant, "user": user, "key": key}


def test_create_api_key_returns_full_key_once(keys_world, client):
    resp = client.post("/api/api-keys", json={"name": "Integration", "scopes": "read,write"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Integration"
    assert data["key"].startswith("pmo_")
    assert data["scopes"] == "read,write"
    assert "won't be shown again" in data["message"]


def test_create_api_key_invalid_scope_422(keys_world, client):
    resp = client.post("/api/api-keys", json={"name": "Bad", "scopes": "root"})
    assert resp.status_code == 422


def test_list_api_keys_masks_key(keys_world, client):
    resp = client.get("/api/api-keys")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "CI key"
    assert row["key_prefix"] == keys_world["key"].key_prefix
    # Never the hash or the full key
    assert "key_hash" not in row and "key" not in row


def test_revoke_api_key(keys_world, client):
    key_id = keys_world["key"].id
    resp = client.delete(f"/api/api-keys/{key_id}")
    assert resp.status_code == 200
    assert resp.json()["revoked"] == key_id
    # Gone from the list
    rows = client.get("/api/api-keys").json()
    assert len(rows) == 0


def test_revoke_other_tenant_key_404(keys_world, client, db, auth_user):
    """Another tenant's API key cannot be revoked — tenant-scoped lookup."""
    from app.models.tenant import Tenant, TenantMembership
    from app.models.user import User

    other = Tenant(name="Other Keys Co", slug="other-keys-co", plan="team")
    db.add(other)
    db.commit()
    db.refresh(other)
    other_user = User(email="o@keys.example.com", name="O", hashed_password="x", system_role="member", active_tenant_id=other.id)
    db.add(other_user)
    db.commit()
    db.refresh(other_user)
    db.add(TenantMembership(user_id=other_user.id, tenant_id=other.id, role="owner"))
    raw = ApiKey.generate_key()
    other_key = ApiKey(
        tenant_id=other.id, name="Theirs",
        key_hash=ApiKey.hash_key(raw), key_prefix=ApiKey.get_prefix(raw),
        scopes="read", created_by=other_user.id,
    )
    db.add(other_key)
    db.commit()
    db.refresh(other_key)

    resp = client.delete(f"/api/api-keys/{other_key.id}")
    assert resp.status_code == 404
    # Still there
    assert db.query(ApiKey).filter(ApiKey.id == other_key.id).first() is not None


def test_api_keys_require_owner_role(client, db, auth_user):
    """A plain member (no owner/admin role) gets 403."""
    from app.models.tenant import Tenant, TenantMembership
    from app.models.user import User
    from app.services.auth import create_access_token

    other = Tenant(name="Member Keys Co", slug="member-keys-co", plan="free")
    db.add(other)
    db.commit()
    db.refresh(other)
    member = User(email="m@keys.example.com", name="M", hashed_password="x", system_role="member", active_tenant_id=other.id)
    db.add(member)
    db.commit()
    db.refresh(member)
    db.add(TenantMembership(user_id=member.id, tenant_id=other.id, role="member"))
    db.commit()

    token = create_access_token({"sub": str(member.id)})
    resp = client.get("/api/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
