"""Tests for the tenant management router + multi-tenant isolation.

Covers: tenant info/branding (owner-gated), member management (invite, role
change, remove — owner/admin only, last-owner protection), switch-tenant
(membership required), admin tenant/user creation (super-admin only), and
the isolation guarantees: tenant A can never read or mutate tenant B's data
through any of these endpoints.
"""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.tenant import Invitation, Tenant, TenantMembership
from app.models.user import User
from app.services.auth import create_access_token, hash_password


@pytest.fixture()
def two_tenants(client, db, auth_user):
    """The shared owner in tenant A; an owner in tenant B with a project."""
    tenant_a = auth_user["tenant"]
    user_a = auth_user["user"]

    tenant_b = Tenant(name="B Co", slug="b-co", plan="enterprise")
    db.add(tenant_b)
    db.commit()
    db.refresh(tenant_b)
    user_b = User(email="owner@b.example.com", name="Owner B", hashed_password=hash_password("OwnerB123!"), system_role="member", active_tenant_id=tenant_b.id)
    db.add(user_b)
    db.commit()
    db.refresh(user_b)
    db.add(TenantMembership(user_id=user_b.id, tenant_id=tenant_b.id, role="owner"))
    project_b = Project(name="B Secret Project", client_id=1, tenant_id=tenant_b.id)
    db.add(project_b)
    db.commit()
    db.refresh(project_b)
    return {"tenant_a": tenant_a, "user_a": user_a, "tenant_b": tenant_b, "user_b": user_b, "project_b": project_b}


def _b_headers(user_b):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_b.id)})}"}


# ── Tenant info & branding ───────────────────────────────────────

def test_get_tenant_info(client, auth_user):
    resp = client.get("/api/tenant")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == auth_user["tenant"].id
    assert data["name"] == "Test Tenant"
    assert data["branding"] == {}


def test_update_tenant_owner_only(client, db, auth_user):
    resp = client.put("/api/tenant", json={"name": "Renamed Co"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed Co"

    # A plain member cannot update tenant info
    member = User(email="m@tenant.example.com", name="M", hashed_password="x", system_role="member", active_tenant_id=auth_user["tenant"].id)
    db.add(member)
    db.commit()
    db.refresh(member)
    db.add(TenantMembership(user_id=member.id, tenant_id=auth_user["tenant"].id, role="member"))
    db.commit()
    token = create_access_token({"sub": str(member.id)})
    resp = client.put("/api/tenant", json={"name": "Hijacked"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_update_branding(client, auth_user):
    resp = client.put("/api/tenant/branding", json={"primary_color": "#6366f1", "app_name": "PMO"})
    assert resp.status_code == 200
    branding = resp.json()["branding"]
    assert branding["primary_color"] == "#6366f1"
    assert branding["app_name"] == "PMO"
    # Hide-powered-by is Enterprise only — the fixture tenant is enterprise
    resp = client.put("/api/tenant/branding", json={"hide_powered_by": True})
    assert resp.json()["branding"]["hide_powered_by"] is True


def test_update_branding_hide_powered_by_not_enterprise(client, db, auth_user):
    """A non-enterprise tenant cannot set hide_powered_by."""
    tenant = auth_user["tenant"]
    tenant.plan = "team"
    db.commit()
    resp = client.put("/api/tenant/branding", json={"hide_powered_by": True})
    assert resp.status_code == 200
    assert "hide_powered_by" not in resp.json()["branding"]
    tenant.plan = "enterprise"  # restore for other tests (fresh DB per test anyway)
    db.commit()


# ── Membership & switching ───────────────────────────────────────

def test_switch_tenant_membership_required(client, two_tenants):
    """A user can only switch to a tenant they belong to."""
    resp = client.post("/api/auth/switch-tenant", json={"tenant_id": two_tenants["tenant_b"].id})
    assert resp.status_code == 403


def test_my_tenants_lists_both_memberships(client, two_tenants, db):
    """A user in two tenants sees both in /auth/my-tenants."""
    db.add(TenantMembership(user_id=two_tenants["user_a"].id, tenant_id=two_tenants["tenant_b"].id, role="member"))
    db.commit()
    resp = client.get("/api/auth/my-tenants")
    assert resp.status_code == 200
    ids = {t["id"] for t in resp.json()}
    assert two_tenants["tenant_a"].id in ids
    assert two_tenants["tenant_b"].id in ids


# ── Team management ──────────────────────────────────────────────

def test_invite_and_accept_flow(client, two_tenants, db):
    """Owner invites → invitation is pending → accept creates membership + token."""
    resp = client.post("/api/tenant/invite", json={"email": "new@invite.example.com", "role": "member"})
    assert resp.status_code == 201
    invite = resp.json()
    assert invite["status"] == "pending"

    # The raw token is not in the API response (only in the DB row)
    invitation = db.query(Invitation).filter(Invitation.email == "new@invite.example.com").first()
    assert invitation is not None

    # Accept without auth (token-based flow)
    accept = client.post("/api/tenant/accept-invite", json={
        "token": invitation.token, "name": "New Member", "password": "Member123!",
    })
    assert accept.status_code == 200
    data = accept.json()
    assert data["token"]
    assert data["tenant_id"] == two_tenants["tenant_a"].id
    assert invitation.status == "accepted"


def test_invite_requires_owner_role(client, db, auth_user):
    member = User(email="inv@tenant.example.com", name="M", hashed_password="x", system_role="member", active_tenant_id=auth_user["tenant"].id)
    db.add(member)
    db.commit()
    db.refresh(member)
    db.add(TenantMembership(user_id=member.id, tenant_id=auth_user["tenant"].id, role="member"))
    db.commit()
    token = create_access_token({"sub": str(member.id)})
    resp = client.post("/api/tenant/invite", json={"email": "x@x.example.com"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_duplicate_invite_400(client, two_tenants):
    client.post("/api/tenant/invite", json={"email": "dup@invite.example.com"})
    resp = client.post("/api/tenant/invite", json={"email": "dup@invite.example.com"})
    assert resp.status_code == 400


def test_remove_member_last_owner_protected(client, two_tenants):
    """The only owner cannot be removed."""
    resp = client.delete(f"/api/tenant/members/{two_tenants['user_a'].id}")
    assert resp.status_code == 400
    assert "transfer ownership" in resp.json()["detail"].lower()


def test_change_member_role(client, two_tenants, db):
    member = User(email="role@tenant.example.com", name="R", hashed_password="x", system_role="member", active_tenant_id=two_tenants["tenant_a"].id)
    db.add(member)
    db.commit()
    db.refresh(member)
    db.add(TenantMembership(user_id=member.id, tenant_id=two_tenants["tenant_a"].id, role="member"))
    db.commit()
    resp = client.put(f"/api/tenant/members/{member.id}?role=admin")
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_list_members(client, two_tenants, db):
    member = User(email="list@tenant.example.com", name="L", hashed_password="x", system_role="member", active_tenant_id=two_tenants["tenant_a"].id)
    db.add(member)
    db.commit()
    db.refresh(member)
    db.add(TenantMembership(user_id=member.id, tenant_id=two_tenants["tenant_a"].id, role="member"))
    db.commit()
    rows = client.get("/api/tenant/members").json()
    emails = {r["user_email"] for r in rows}
    assert "list@tenant.example.com" in emails


# ── Admin endpoints (super-admin only) ───────────────────────────

def test_admin_create_tenant_end_to_end(client):
    resp = client.post("/api/admin/tenants", json={
        "tenant_name": "Fresh Co",
        "owner_name": "Fresh Owner",
        "owner_email": "fresh@example.com",
        "owner_password": "Fresh12345!",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["tenant_slug"] == "fresh-co"
    assert data["plan"] == "free"


def test_admin_create_user(client, two_tenants):
    resp = client.post(f"/api/admin/tenants/{two_tenants['tenant_b'].id}/users", json={
        "email": "added@b.example.com", "name": "Added", "password": "Added12345!", "role": "member",
    })
    assert resp.status_code == 201
    assert resp.json()["role"] == "member"


def test_admin_create_tenant_requires_super_admin(client, two_tenants):
    """Tenant B's owner (not super admin) gets 403 from admin endpoints."""
    resp = client.post(
        "/api/admin/tenants",
        json={"tenant_name": "Nope", "owner_name": "N", "owner_email": "n@n.example.com", "owner_password": "Nope12345!"},
        headers=_b_headers(two_tenants["user_b"]),
    )
    assert resp.status_code == 403


# ── Multi-tenant isolation ───────────────────────────────────────

def test_tenant_b_data_invisible_to_tenant_a(client, two_tenants):
    """Tenant A's owner cannot see tenant B's project through scoping."""
    resp = client.get(f"/api/projects/{two_tenants['project_b'].id}")
    assert resp.status_code == 404


def test_isolation_via_switch_then_read(client, two_tenants):
    """Even after switching to tenant B... you can't — membership is checked."""
    resp = client.post("/api/auth/switch-tenant", json={"tenant_id": two_tenants["tenant_b"].id})
    assert resp.status_code == 403


def test_get_tenant_limits(client, two_tenants):
    resp = client.get("/api/tenant/limits")
    assert resp.status_code == 200
    data = resp.json()
    assert "limits" in data and "current" in data
    assert data["current"]["users"] >= 1
