"""Slice 7 — R3 decision records: any call, one place, searchable, chained.

Covers: create (row + hash-linked chain entry), the tenant-scoped list
(another tenant's decision is invisible), ?q= search across
title/decision/rationale, the ?project_id=/?item_id= filters, pagination
newest first, the content-only edit (made_at/made_by immutable), supersede
(old superseded + successor chained_from_id + chain entries for both), the
permission-gated delete (with its own chain entry), the gate linkage
(approval_request_id stored), and source validation.
"""
from fastapi.testclient import TestClient

import app.models  # noqa: F401 — register all models with Base
from app.main import app
from app.models.approval import ApprovalRequest
from app.models.artifact_chain import ArtifactChain
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.decision_record import DecisionRecord
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services.artifact_chain import verify_chain
from app.services.auth import create_access_token, hash_password

# --------------------------------------------------------------------------- helpers

def _project(db, tenant, user, name="Decisions P") -> Project:
    """Projects require a client (NOT NULL FK) — seed one for the test."""
    c = Client(tenant_id=tenant.id, name=f"Client {name}")
    db.add(c)
    db.commit()
    db.refresh(c)
    p = Project(
        tenant_id=tenant.id, name=name, status="active",
        client_id=c.id, project_manager_id=user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _item(db, tenant, project, title="Chained item") -> BacklogItem:
    it = BacklogItem(tenant_id=tenant.id, project_id=project.id, title=title, status="Draft")
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _approval(db, tenant, project, title="Release gate") -> ApprovalRequest:
    ar = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id, title=title,
        request_type="release", status="Pending",
    )
    db.add(ar)
    db.commit()
    db.refresh(ar)
    return ar


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


def _chain(db, decision_id):
    return (
        db.query(ArtifactChain)
        .filter(ArtifactChain.entity_type == "decision", ArtifactChain.entity_id == decision_id)
        .order_by(ArtifactChain.seq)
        .all()
    )


# --------------------------------------------------------------------------- 1. create

def test_create_persists_row_and_chain_entry(client, db, auth_user):
    p = _project(db, auth_user["tenant"], auth_user["user"])
    resp = client.post("/api/decisions", json={
        "title": "Ship on Friday",
        "decision": "Release the module behind a flag",
        "rationale": "The suite is green and the risk is contained",
        "alternatives": "Wait for the next sprint",
        "project_id": p.id,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "Ship on Friday"
    assert body["status"] == "active" and body["source"] == "manual"
    assert body["made_by"] == auth_user["user"].id
    assert body["made_at"]  # server default now()
    assert body["project_id"] == p.id
    assert body["chain"]["seq"] == 1 and body["chain"]["hash"]

    row = db.query(DecisionRecord).filter(DecisionRecord.id == body["id"]).first()
    assert row is not None and row.tenant_id == auth_user["tenant"].id
    entry = _chain(db, body["id"])
    assert [e.action for e in entry] == ["created"]
    assert verify_chain(db, auth_user["tenant"].id, "decision", body["id"])["valid"]


def test_create_requires_title_and_decision(client):
    assert client.post("/api/decisions", json={"title": "No decision body"}).status_code == 422
    assert client.post("/api/decisions", json={"decision": "No title"}).status_code == 422
    assert client.post("/api/decisions", json={"title": "", "decision": ""}).status_code == 422


def test_source_validated(client):
    resp = client.post("/api/decisions", json={
        "title": "t", "decision": "d", "source": "carrier-pigeon",
    })
    assert resp.status_code == 422


# --------------------------------------------------------------------------- 2. tenant scope

def test_list_is_tenant_scoped(client, db, auth_user):
    client.post("/api/decisions", json={"title": "Ours", "decision": "Visible only to us"})

    other = _second_tenant(db)
    tc2, _ = _second_client(
        db, other, "other@pmo.test", system_role="super_admin", role="owner",
    )
    r2 = tc2.post("/api/decisions", json={"title": "Theirs", "decision": "Invisible to us"})
    assert r2.status_code == 201, r2.text

    ours = client.get("/api/decisions").json()
    titles = [d["title"] for d in ours["decisions"]]
    assert "Ours" in titles and "Theirs" not in titles
    theirs = tc2.get("/api/decisions").json()
    assert [d["title"] for d in theirs["decisions"]] == ["Theirs"]


def test_get_single_and_cross_tenant_404(client, db, auth_user):
    created = client.post("/api/decisions", json={"title": "One", "decision": "d"}).json()
    assert client.get(f"/api/decisions/{created['id']}").json()["id"] == created["id"]
    assert client.get("/api/decisions/99999").status_code == 404

    other = _second_tenant(db)
    tc2, _ = _second_client(db, other, "x@pmo.test", system_role="super_admin", role="owner")
    theirs = tc2.post("/api/decisions", json={"title": "Theirs", "decision": "d"}).json()
    # another tenant's record is invisible by id too
    assert client.get(f"/api/decisions/{theirs['id']}").status_code == 404


# --------------------------------------------------------------------------- 3. search + filters

def test_search_across_title_decision_rationale(client, db, auth_user):
    client.post("/api/decisions", json={"title": "Postgres migration", "decision": "Ship in batches"})
    client.post("/api/decisions", json={
        "title": "Caching layer", "decision": "Use Redis for the rate limiter",
    })
    client.post("/api/decisions", json={
        "title": "Async updates", "decision": "Standups become written",
        "rationale": "Redis-style per-thread channels span timezones",
    })
    client.post("/api/decisions", json={"title": "Unrelated", "decision": "Ship on Monday"})
    rows = client.get("/api/decisions", params={"q": "redis"}).json()["decisions"]
    # ?q= hits the decision text and the rationale — not the title only
    assert set(d["title"] for d in rows) == {"Caching layer", "Async updates"}


def test_project_filter(client, db, auth_user):
    tenant, user = auth_user["tenant"], auth_user["user"]
    p1 = _project(db, tenant, user, "P One")
    p2 = _project(db, tenant, user, "P Two")
    client.post("/api/decisions", json={"title": "For one", "decision": "d", "project_id": p1.id})
    client.post("/api/decisions", json={"title": "For two", "decision": "d", "project_id": p2.id})
    # any call can be projectless
    client.post("/api/decisions", json={"title": "Projectless", "decision": "d"})

    only_p1 = client.get("/api/decisions", params={"project_id": p1.id}).json()
    assert [d["title"] for d in only_p1["decisions"]] == ["For one"]
    everything = client.get("/api/decisions").json()
    assert "Projectless" in [d["title"] for d in everything["decisions"]]


def test_item_filter(client, db, auth_user):
    tenant, user = auth_user["tenant"], auth_user["user"]
    p = _project(db, tenant, user, "Items P")
    it1 = _item(db, tenant, p, "Item one")
    it2 = _item(db, tenant, p, "Item two")
    client.post("/api/decisions", json={"title": "Chained to one", "decision": "d", "item_id": it1.id})
    client.post("/api/decisions", json={"title": "Chained to two", "decision": "d", "item_id": it2.id})
    rows = client.get("/api/decisions", params={"item_id": it1.id}).json()["decisions"]
    assert [d["title"] for d in rows] == ["Chained to one"]


def test_list_paginated_newest_first(client, db, auth_user):
    for i in range(3):
        client.post("/api/decisions", json={"title": f"Call {i}", "decision": f"d{i}"})
    body = client.get("/api/decisions", params={"per_page": 2}).json()
    assert body["total"] == 3 and body["total_pages"] == 2
    assert [d["title"] for d in body["decisions"]] == ["Call 2", "Call 1"]
    page2 = client.get("/api/decisions", params={"per_page": 2, "page": 2}).json()
    assert [d["title"] for d in page2["decisions"]] == ["Call 0"]


# --------------------------------------------------------------------------- 4. update

def test_update_edits_content_and_keeps_made_at_made_by_immutable(client, db, auth_user):
    user = auth_user["user"]
    created = client.post("/api/decisions", json={"title": "Before", "decision": "d"}).json()
    resp = client.put(f"/api/decisions/{created['id']}", json={
        "title": "After", "rationale": "why now", "alternatives": "the others",
        "made_at": "1999-01-01T00:00:00", "made_by": 99999,  # dropped — immutable
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "After"
    assert body["rationale"] == "why now" and body["alternatives"] == "the others"
    assert body["made_at"] == created["made_at"]
    assert body["made_by"] == user.id


# --------------------------------------------------------------------------- 5. supersede

def test_supersede_chains_and_marks_old(client, db, auth_user):
    tenant = auth_user["tenant"]
    created = client.post("/api/decisions", json={
        "title": "v1", "decision": "Ship manually", "source": "manual",
    }).json()
    resp = client.post(f"/api/decisions/{created['id']}/supersede", json={
        "title": "v2", "decision": "Automate the release", "source": "gate",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["chained_from_id"] == created["id"]
    assert body["status"] == "active"

    old = client.get(f"/api/decisions/{created['id']}").json()
    assert old["status"] == "superseded"

    # chain entries for BOTH records
    assert [e.action for e in _chain(db, body["id"])] == ["created"]
    assert [e.action for e in _chain(db, created["id"])] == ["created", "superseded"]
    assert verify_chain(db, tenant.id, "decision", body["id"])["valid"]
    assert verify_chain(db, tenant.id, "decision", created["id"])["valid"]


def test_supersede_rejects_already_superseded(client):
    created = client.post("/api/decisions", json={"title": "v1", "decision": "d"}).json()
    assert client.post(
        f"/api/decisions/{created['id']}/supersede",
        json={"title": "v2", "decision": "d2"},
    ).status_code == 201
    assert client.post(
        f"/api/decisions/{created['id']}/supersede",
        json={"title": "v3", "decision": "d3"},
    ).status_code == 422


# --------------------------------------------------------------------------- 6. delete (permission-gated)

def test_delete_is_permission_gated(client, db, auth_user):
    tenant, user = auth_user["tenant"], auth_user["user"]
    p = _project(db, tenant, user, "Delete P")
    created = client.post("/api/decisions", json={
        "title": "Kill me", "decision": "d", "project_id": p.id,
    }).json()

    # a plain member (no manage permission) is refused
    member_tc, _ = _second_client(db, tenant, "deleter@pmo.test")
    assert member_tc.delete(f"/api/decisions/{created['id']}").status_code == 403

    # the house owner (PM of the project / tenant admin) can — and the delete
    # itself is recorded in the chain before the row goes
    assert client.delete(f"/api/decisions/{created['id']}").status_code == 200
    assert db.query(DecisionRecord).filter(DecisionRecord.id == created["id"]).first() is None
    assert [e.action for e in _chain(db, created["id"])] == ["created", "deleted"]


# --------------------------------------------------------------------------- 7. gate linkage

def test_gate_linkage_stores_approval_request(client, db, auth_user):
    tenant, user = auth_user["tenant"], auth_user["user"]
    p = _project(db, tenant, user, "Gate P")
    ar = _approval(db, tenant, p, "Release gate — Phase 2")
    resp = client.post("/api/decisions", json={
        "title": "Gate decision", "decision": "Approved for UAT", "source": "gate",
        "approval_request_id": ar.id, "project_id": p.id,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["approval_request_id"] == ar.id
    assert body["source"] == "gate"
    row = db.query(DecisionRecord).filter(DecisionRecord.id == body["id"]).first()
    assert row.approval_request_id == ar.id
