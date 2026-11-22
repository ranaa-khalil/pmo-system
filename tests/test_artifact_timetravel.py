"""Artifact chain time-travel — the `at` as-of param + the tenant-wide timeline.

GET /api/artifacts/{entity_type}/{entity_id}?at=<ISO>    — chain AS OF a moment
GET /api/artifacts/{entity_type}/{entity_id}/verify?at=  — verify the chain
                                                           PREFIX up to `at`
GET /api/artifacts/timeline                              — ledger stream
      (?project_id= filter, ?since=/ ?until= window, limit/offset pagination)

Time-travel is read-only: created_at is backdated directly in the DB (the
hash does not cover created_at, so backdating is chain-safe) and the write
paths are never touched.
"""
from datetime import UTC, datetime, timedelta, timezone

import pytest

import app.models  # noqa: F401


def _backdate(db, minutes_per_row):
    """Backdate chain rows (in insert order): row i gets minutes_per_row[i] ago.

    The hash covers prev_hash|entity|action|payload — never created_at — so
    backdating does not disturb the chain.
    """
    from app.models.artifact_chain import ArtifactChain

    rows = db.query(ArtifactChain).order_by(ArtifactChain.id).all()
    for row, minutes in zip(rows, minutes_per_row, strict=False):
        row.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes)
    db.commit()


@pytest.fixture
def three_entries(db, auth_user):
    """3 chain entries on backlog_item/42, backdated 30/20/10 min ago.

    Returns the as-of moment between the 2nd and 3rd entry (15 min ago).
    """
    from app.services.artifact_chain import append_artifact

    for action, payload in [("created", {"v": 1}), ("advanced", {"to": "Design"}), ("approved", {"by": "PM"})]:
        append_artifact(db, auth_user["tenant"].id, "backlog_item", 42, action, payload=payload)
    db.commit()
    _backdate(db, [30, 20, 10])
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=15)


# ==================== `at` — the chain AS OF a moment ====================


def test_at_returns_chain_prefix(client, three_entries):
    resp = client.get("/api/artifacts/backlog_item/42", params={"at": three_entries.isoformat()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_of"] == three_entries.isoformat()  # echo
    assert [e["action"] for e in body["entries"]] == ["created", "advanced"]  # exactly the prefix
    assert body["length"] == 2
    assert body["valid"] is True
    assert body["entries"][1]["prev_hash"] == body["entries"][0]["hash"]  # still linked


def test_at_absent_returns_full_chain_without_echo(client, three_entries):
    resp = client.get("/api/artifacts/backlog_item/42")
    assert resp.status_code == 200
    body = resp.json()
    assert [e["action"] for e in body["entries"]] == ["created", "advanced", "approved"]
    assert body["length"] == 3
    assert "as_of" not in body  # unchanged shape without ?at


def test_at_accepts_timezone_offset(client, three_entries):
    aware = three_entries.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=3)))
    resp = client.get("/api/artifacts/backlog_item/42", params={"at": aware.isoformat()})
    assert resp.status_code == 200
    body = resp.json()
    assert [e["action"] for e in body["entries"]] == ["created", "advanced"]  # same instant, same prefix


def test_at_after_all_entries_returns_full_chain(client, three_entries):
    at = (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)).isoformat()
    resp = client.get("/api/artifacts/backlog_item/42", params={"at": at})
    body = resp.json()
    assert [e["action"] for e in body["entries"]] == ["created", "advanced", "approved"]


# ==================== `at` — verify the chain PREFIX ====================


def test_as_of_verify_clean_prefix(client, three_entries):
    resp = client.get("/api/artifacts/backlog_item/42/verify", params={"at": three_entries.isoformat()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["length"] == 2
    assert body["broken_at"] is None
    assert "as_of" in body


def test_as_of_verify_ignores_tamper_after_at(client, db, three_entries):
    from app.models.artifact_chain import ArtifactChain

    row = db.query(ArtifactChain).filter(ArtifactChain.entity_type == "backlog_item", ArtifactChain.seq == 3).first()
    row.payload = {"by": "Tampered"}
    db.commit()

    # The tampered seq-3 entry is AFTER `at` — the as-of prefix is still clean
    resp = client.get("/api/artifacts/backlog_item/42/verify", params={"at": three_entries.isoformat()})
    assert resp.json()["valid"] is True

    # The full verify still catches the tampering
    resp = client.get("/api/artifacts/backlog_item/42/verify")
    assert resp.json()["valid"] is False
    assert resp.json()["broken_at"] == 3


def test_as_of_verify_catches_tamper_within_prefix(client, db, three_entries):
    from app.models.artifact_chain import ArtifactChain

    row = db.query(ArtifactChain).filter(ArtifactChain.entity_type == "backlog_item", ArtifactChain.seq == 1).first()
    row.payload = {"v": "rewritten"}
    db.commit()

    resp = client.get("/api/artifacts/backlog_item/42/verify", params={"at": three_entries.isoformat()})
    body = resp.json()
    assert body["valid"] is False  # tampering INSIDE the prefix fails the as-of verify
    assert body["broken_at"] == 1


# ==================== /timeline — the tenant-wide ledger ====================


def test_timeline_lists_tenant_stream_newest_first(client, db, auth_user):
    from app.services.artifact_chain import append_artifact

    append_artifact(db, auth_user["tenant"].id, "backlog_item", 1, "created", actor_name="Rana", payload={})
    append_artifact(db, auth_user["tenant"].id, "approval_request", 2, "approved", actor_name="Sam", payload={})
    db.commit()

    resp = client.get("/api/artifacts/timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["entries"]) == 2
    first = body["entries"][0]
    assert (first["entity_type"], first["entity_id"], first["action"]) == ("approval_request", 2, "approved")
    for entry in body["entries"]:
        assert {"id", "entity_type", "entity_id", "action", "created_at", "actor"} <= set(entry)
    assert first["actor"] == "Sam"


def test_timeline_scoped_to_tenant(client, db, auth_user):
    from app.services.artifact_chain import append_artifact

    append_artifact(db, auth_user["tenant"].id + 999, "backlog_item", 5, "created", payload={})
    db.commit()
    body = client.get("/api/artifacts/timeline").json()
    assert body["total"] == 0  # other tenant's entries invisible
    assert body["entries"] == []


def test_timeline_requires_auth(anon_client):
    resp = anon_client.get("/api/artifacts/timeline")
    assert resp.status_code in (401, 403)


@pytest.fixture
def two_projects(db, auth_user):
    from app.models.project import Project

    pa = Project(tenant_id=auth_user["tenant"].id, client_id=auth_user["user"].id, name="Proj A")
    pb = Project(tenant_id=auth_user["tenant"].id, client_id=auth_user["user"].id, name="Proj B")
    db.add_all([pa, pb])
    db.commit()
    db.refresh(pa)
    db.refresh(pb)
    return pa, pb


def test_timeline_project_filter(client, db, auth_user, two_projects):
    from app.models.approval import ApprovalRequest
    from app.models.backlog_item import BacklogItem
    from app.services.artifact_chain import append_artifact

    pa, pb = two_projects
    item_a = BacklogItem(tenant_id=auth_user["tenant"].id, project_id=pa.id, title="A item")
    item_b = BacklogItem(tenant_id=auth_user["tenant"].id, project_id=pb.id, title="B item")
    db.add_all([item_a, item_b])
    db.commit()
    db.refresh(item_a)
    db.refresh(item_b)
    approval = ApprovalRequest(
        tenant_id=auth_user["tenant"].id, project_id=pa.id, title="Gate A", request_type="phase_gate"
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    append_artifact(db, auth_user["tenant"].id, "backlog_item", item_a.id, "created", payload={})
    append_artifact(db, auth_user["tenant"].id, "backlog_item", item_b.id, "created", payload={})
    append_artifact(db, auth_user["tenant"].id, "approval_request", approval.id, "approved", payload={})
    append_artifact(db, auth_user["tenant"].id, "project", pa.id, "created", payload={})
    db.commit()

    body = client.get("/api/artifacts/timeline", params={"project_id": pa.id}).json()
    assert body["total"] == 3
    scopes = {(e["entity_type"], e["entity_id"]) for e in body["entries"]}
    assert ("backlog_item", item_a.id) in scopes
    assert ("approval_request", approval.id) in scopes
    assert ("project", pa.id) in scopes
    assert ("backlog_item", item_b.id) not in scopes  # project B's work invisible


def test_timeline_pagination(client, db, auth_user):
    from app.services.artifact_chain import append_artifact

    for i in range(5):
        append_artifact(db, auth_user["tenant"].id, "backlog_item", 1, f"step{i}", payload={})
    db.commit()

    page1 = client.get("/api/artifacts/timeline", params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/api/artifacts/timeline", params={"limit": 2, "offset": 2}).json()
    page3 = client.get("/api/artifacts/timeline", params={"limit": 2, "offset": 4}).json()
    assert page1["total"] == 5
    assert [e["action"] for e in page1["entries"]] == ["step4", "step3"]
    assert [e["action"] for e in page2["entries"]] == ["step2", "step1"]
    assert [e["action"] for e in page3["entries"]] == ["step0"]


def test_timeline_since_until_window(client, db, auth_user):
    from app.services.artifact_chain import append_artifact

    for action in ["created", "advanced", "approved", "released"]:
        append_artifact(db, auth_user["tenant"].id, "backlog_item", 1, action, payload={})
    db.commit()
    _backdate(db, [40, 25, 15, 5])

    params = {
        "since": (datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)).isoformat(),
        "until": (datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)).isoformat(),
    }
    body = client.get("/api/artifacts/timeline", params=params).json()
    assert body["total"] == 2
    assert [e["action"] for e in body["entries"]] == ["approved", "advanced"]  # newest first in-window
