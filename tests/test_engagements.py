"""Slice 11 — R4 client engagements: the contract wrapper around one client's projects.

Covers: create (row + hash-linked chain entry), name/client_id required, the
client_id tenancy check (a foreign client → 400), the tenant-scoped list with
?client_id=/ ?status= filters, pagination newest first, the projects rollup
(engagement → its projects; a foreign-tenant project never appears), the
content edit (client_id immutable), status validation, the permission-gated
delete (with its own chain entry), cross-tenant invisibility (404 on
GET/PUT/DELETE), and the anon 401 path.
"""
from fastapi.testclient import TestClient

import app.models  # noqa: F401 — register all models with Base
from app.main import app
from app.models.artifact_chain import ArtifactChain
from app.models.client import Client
from app.models.engagement import Engagement
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services.artifact_chain import verify_chain
from app.services.auth import create_access_token, hash_password

# --------------------------------------------------------------------------- helpers


def _client_row(db, tenant, name="Engagement Client") -> Client:
    c = Client(tenant_id=tenant.id, name=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _project(db, tenant, client_id, name="Client project") -> Project:
    p = Project(tenant_id=tenant.id, name=name, status="Active", client_id=client_id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _second_client(db, tenant, email, system_role="member", role="member"):
    """A second user (own token) inside the given tenant."""
    u = User(
        email=email, name=f"User {email}",
        hashed_password=hash_password("TestPass123!"),
        system_role=system_role, active_tenant_id=tenant.id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(TenantMembership(user_id=u.id, tenant_id=tenant.id, role=role))
    db.commit()
    tc = TestClient(app)
    tc.headers.update({"Authorization": f"Bearer {create_access_token({'sub': str(u.id)})}"})
    return tc, u


def _second_tenant(db):
    t = Tenant(name="Other Tenant", slug="other-tenant", plan="enterprise", status="active")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _chain(db, engagement_id):
    return (
        db.query(ArtifactChain)
        .filter(ArtifactChain.entity_type == "engagement", ArtifactChain.entity_id == engagement_id)
        .order_by(ArtifactChain.seq)
        .all()
    )


# --------------------------------------------------------------------------- 1. create


def test_create_persists_row_and_chain_entry(client, db, auth_user):
    c = _client_row(db, auth_user["tenant"])
    resp = client.post("/api/engagements", json={
        "name": "PNU Cloud retainer",
        "client_id": c.id,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "PNU Cloud retainer"
    assert body["client_id"] == c.id
    assert body["tenant_id"] == auth_user["tenant"].id
    assert body["status"] == "active"  # default
    assert body["contract_value"] is None and body["pmo_lead_id"] is None
    assert body["chain"]["seq"] == 1 and body["chain"]["hash"]

    row = db.query(Engagement).filter(Engagement.id == body["id"]).first()
    assert row is not None and row.tenant_id == auth_user["tenant"].id
    entry = _chain(db, body["id"])
    assert [e.action for e in entry] == ["created"]
    assert verify_chain(db, auth_user["tenant"].id, "engagement", body["id"])["valid"]


def test_create_requires_name_and_client_id(client):
    assert client.post("/api/engagements", json={"name": "No client"}).status_code == 422
    assert client.post("/api/engagements", json={"client_id": 1}).status_code == 422
    assert client.post("/api/engagements", json={"name": "", "client_id": 1}).status_code == 422


def test_create_rejects_foreign_client(client, db, auth_user):
    other = _second_tenant(db)
    foreign = _client_row(db, other, name="Foreign Client")

    # another tenant's client is refused (the kpi_id tenancy pattern)
    resp = client.post("/api/engagements", json={"name": "Rogue", "client_id": foreign.id})
    assert resp.status_code == 400, resp.text
    # and so is a client id that does not exist at all
    assert client.post("/api/engagements", json={"name": "Ghost", "client_id": 99999}).status_code == 400


def test_create_with_contract_fields_and_lead(client, db, auth_user):
    tenant, user = auth_user["tenant"], auth_user["user"]
    c = _client_row(db, tenant)
    resp = client.post("/api/engagements", json={
        "name": "CloudGate build",
        "client_id": c.id,
        "status": "paused",
        "start_date": "2026-01-15",
        "end_date": "2026-12-31",
        "contract_value": "SAR 250,000",
        "pmo_lead_id": user.id,
        "notes": "Renews annually",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "paused"
    assert body["start_date"] == "2026-01-15" and body["end_date"] == "2026-12-31"
    assert body["contract_value"] == "SAR 250,000"  # currency-agnostic string
    assert body["pmo_lead_id"] == user.id
    assert body["notes"] == "Renews annually"


# --------------------------------------------------------------------------- 2. list


def test_list_is_tenant_scoped(client, db, auth_user):
    c = _client_row(db, auth_user["tenant"])
    client.post("/api/engagements", json={"name": "Ours", "client_id": c.id})

    other = _second_tenant(db)
    tc2, _ = _second_client(db, other, "other@pmo.test", system_role="super_admin", role="owner")
    foreign_c = _client_row(db, other, name="Their client")
    r2 = tc2.post("/api/engagements", json={"name": "Theirs", "client_id": foreign_c.id})
    assert r2.status_code == 201, r2.text

    ours = client.get("/api/engagements").json()
    names = [e["name"] for e in ours["engagements"]]
    assert "Ours" in names and "Theirs" not in names
    theirs = tc2.get("/api/engagements").json()
    assert [e["name"] for e in theirs["engagements"]] == ["Theirs"]


def test_list_filters_by_client_and_status(client, db, auth_user):
    c1 = _client_row(db, auth_user["tenant"], name="Client One")
    c2 = _client_row(db, auth_user["tenant"], name="Client Two")
    client.post("/api/engagements", json={"name": "A", "client_id": c1.id, "status": "active"})
    client.post("/api/engagements", json={"name": "B", "client_id": c1.id, "status": "closed"})
    client.post("/api/engagements", json={"name": "C", "client_id": c2.id, "status": "active"})

    only_c1 = client.get("/api/engagements", params={"client_id": c1.id}).json()
    assert [e["name"] for e in only_c1["engagements"]] == ["B", "A"]  # newest first
    only_c2 = client.get("/api/engagements", params={"client_id": c2.id}).json()
    assert [e["name"] for e in only_c2["engagements"]] == ["C"]
    closed = client.get("/api/engagements", params={"status": "closed"}).json()
    assert [e["name"] for e in closed["engagements"]] == ["B"]
    paused = client.get("/api/engagements", params={"status": "paused"}).json()
    assert paused["engagements"] == []


def test_list_paginated_newest_first(client, db, auth_user):
    c = _client_row(db, auth_user["tenant"])
    for i in range(3):
        client.post("/api/engagements", json={"name": f"Engagement {i}", "client_id": c.id})
    body = client.get("/api/engagements", params={"per_page": 2}).json()
    assert body["total"] == 3 and body["total_pages"] == 2
    assert [e["name"] for e in body["engagements"]] == ["Engagement 2", "Engagement 1"]
    page2 = client.get("/api/engagements", params={"per_page": 2, "page": 2}).json()
    assert [e["name"] for e in page2["engagements"]] == ["Engagement 0"]


# --------------------------------------------------------------------------- 3. get + rollup


def test_get_returns_projects_rollup(client, db, auth_user):
    tenant = auth_user["tenant"]
    c = _client_row(db, tenant)
    p1 = _project(db, tenant, c.id, name="PNU Cloud")
    p2 = _project(db, tenant, c.id, name="PNU Portal")
    other_client = _client_row(db, tenant, name="Other Client")
    _project(db, tenant, other_client.id, name="Unrelated project")

    created = client.post("/api/engagements", json={"name": "Retainer", "client_id": c.id}).json()
    body = client.get(f"/api/engagements/{created['id']}").json()
    assert body["id"] == created["id"] and body["name"] == "Retainer"
    assert body["projects"]["count"] == 2
    assert {p["id"] for p in body["projects"]["items"]} == {p1.id, p2.id}
    assert all(set(p) == {"id", "name", "status"} for p in body["projects"]["items"])


def test_rollup_never_leaks_a_foreign_tenant_project(client, db, auth_user):
    tenant = auth_user["tenant"]
    c = _client_row(db, tenant)
    ours = _project(db, tenant, c.id, name="Our project")

    # a rogue row: another tenant's project pointing at OUR client_id — the
    # rollup is tenant-filtered, so it must never appear
    other = _second_tenant(db)
    rogue = Project(tenant_id=other.id, name="Rogue project", status="Active", client_id=c.id)
    db.add(rogue)
    db.commit()
    db.refresh(rogue)

    created = client.post("/api/engagements", json={"name": "Scoped", "client_id": c.id}).json()
    body = client.get(f"/api/engagements/{created['id']}").json()
    assert body["projects"]["count"] == 1
    assert [p["id"] for p in body["projects"]["items"]] == [ours.id]


# --------------------------------------------------------------------------- 4. update


def test_update_edits_fields_and_keeps_client_id_immutable(client, db, auth_user):
    tenant, user = auth_user["tenant"], auth_user["user"]
    c = _client_row(db, tenant)
    other_client = _client_row(db, tenant, name="Other Client")
    created = client.post("/api/engagements", json={"name": "Before", "client_id": c.id}).json()

    resp = client.put(f"/api/engagements/{created['id']}", json={
        "name": "After",
        "status": "paused",
        "start_date": "2026-02-01",
        "end_date": "2026-11-30",
        "contract_value": "USD 80k",
        "notes": "renewal pending",
        "pmo_lead_id": user.id,
        "client_id": other_client.id,  # dropped — immutable
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "After" and body["status"] == "paused"
    assert body["start_date"] == "2026-02-01" and body["end_date"] == "2026-11-30"
    assert body["contract_value"] == "USD 80k" and body["notes"] == "renewal pending"
    assert body["pmo_lead_id"] == user.id
    assert body["client_id"] == c.id  # unchanged


def test_update_validates_status_and_lead(client, db, auth_user):
    tenant = auth_user["tenant"]
    c = _client_row(db, tenant)
    created = client.post("/api/engagements", json={"name": "One", "client_id": c.id}).json()
    assert client.put(
        f"/api/engagements/{created['id']}", json={"status": "bogus"}
    ).status_code == 422
    assert client.put(
        f"/api/engagements/{created['id']}", json={"pmo_lead_id": 99999}
    ).status_code == 400


# --------------------------------------------------------------------------- 5. delete (permission-gated)


def test_delete_is_permission_gated(client, db, auth_user):
    tenant = auth_user["tenant"]
    c = _client_row(db, tenant)
    created = client.post("/api/engagements", json={"name": "Kill me", "client_id": c.id}).json()

    # a plain member (no manage permission on the client) is refused
    member_tc, _ = _second_client(db, tenant, "deleter@pmo.test")
    assert member_tc.delete(f"/api/engagements/{created['id']}").status_code == 403

    # the house owner (tenant admin) can — and the delete itself is recorded
    # in the chain before the row goes
    assert client.delete(f"/api/engagements/{created['id']}").status_code == 200
    assert db.query(Engagement).filter(Engagement.id == created["id"]).first() is None
    assert [e.action for e in _chain(db, created["id"])] == ["created", "deleted"]


# --------------------------------------------------------------------------- 6. tenancy + auth


def test_cross_tenant_engagement_is_invisible(client, db, auth_user):
    c = _client_row(db, auth_user["tenant"])
    created = client.post("/api/engagements", json={"name": "Secret", "client_id": c.id}).json()

    other = _second_tenant(db)
    tc2, _ = _second_client(db, other, "x@pmo.test", system_role="super_admin", role="owner")
    assert tc2.get(f"/api/engagements/{created['id']}").status_code == 404
    assert tc2.put(f"/api/engagements/{created['id']}", json={"name": "Hijack"}).status_code == 404
    assert tc2.delete(f"/api/engagements/{created['id']}").status_code == 404


def test_anon_gets_401(anon_client):
    assert anon_client.get("/api/engagements").status_code == 401
    assert anon_client.post("/api/engagements", json={"name": "x", "client_id": 1}).status_code == 401
