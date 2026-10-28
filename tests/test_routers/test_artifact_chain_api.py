"""Artifact Chain API — the hash-chained audit trail.

GET /api/artifacts/{entity_type}/{entity_id} — chain + integrity verdict
GET /api/artifacts/{entity_type}/{entity_id}/verify — re-walk the chain
POST /api/artifacts/{entity_type}/{entity_id}/entries — append (service-mediated)
"""
import pytest

import app.models  # noqa: F401


@pytest.fixture
def chain_project(db, auth_user):
    from app.models.project import Project

    p = Project(tenant_id=auth_user["tenant"].id, client_id=auth_user["user"].id, name="Chain P")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_append_and_read_chain(client, db, auth_user, chain_project):
    from app.services.artifact_chain import append_artifact, get_chain  # noqa: F401

    append_artifact(db, auth_user["tenant"].id, "backlog_item", 1, "created",
                    actor_id=auth_user["user"].id, actor_name="Rana", payload={"title": "SSO"})
    append_artifact(db, auth_user["tenant"].id, "backlog_item", 1, "advanced",
                    actor_id=auth_user["user"].id, actor_name="Rana", payload={"to": "Design"})
    db.commit()

    resp = client.get("/api/artifacts/backlog_item/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["length"] == 2
    assert [e["action"] for e in body["entries"]] == ["created", "advanced"]
    assert body["entries"][1]["prev_hash"] == body["entries"][0]["hash"]  # linked


def test_verify_detects_tampering(client, db, auth_user, chain_project):
    from app.models.artifact_chain import ArtifactChain
    from app.services.artifact_chain import append_artifact

    append_artifact(db, auth_user["tenant"].id, "release", 7, "created", payload={"v": "1.0.0"})
    append_artifact(db, auth_user["tenant"].id, "release", 7, "approved", payload={"by": "PM"})
    db.commit()

    # Tamper: rewrite an approved payload after the fact
    row = db.query(ArtifactChain).filter(ArtifactChain.entity_type == "release", ArtifactChain.seq == 2).first()
    row.payload = {"by": "SomeoneElse"}
    db.commit()

    resp = client.get("/api/artifacts/release/7/verify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["broken_at"] == 2


def test_chain_scoped_to_tenant(client, db, auth_user, chain_project):
    from app.services.artifact_chain import append_artifact

    append_artifact(db, auth_user["tenant"].id + 999, "backlog_item", 5, "created", payload={})
    db.commit()
    resp = client.get("/api/artifacts/backlog_item/5")
    assert resp.status_code == 200
    assert resp.json()["length"] == 0  # other tenant's entries invisible


def test_append_via_api(client, db, auth_user, chain_project):
    resp = client.post("/api/artifacts/backlog_item/9/entries", json={
        "action": "updated",
        "payload": {"status": "In Progress"},
        "artifact_type": "state_change",
    })
    assert resp.status_code == 201
    assert resp.json()["seq"] == 1
    assert resp.json()["hash"]
