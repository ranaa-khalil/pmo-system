"""Release machine service tests — the ONE advance machine (Rethink v2 F1).

The advance state machine lives once in app/services/release_machine.py; the
releases + backlog routers delegate to it. These tests pin both halves:

- Service unit: advancing a backlog item through the effective template's
  phases via the SERVICE lands the same artifact-chain entries, in the same
  order and with the same payloads, as the router path produces (the chain
  never forks); the release gate flow runs through the service with the
  byte-identical 400 guards.
- Delegation: each router path invokes the service exactly once with the
  fetched objects; the tenant-scoped fetch + 404 stay in the router.
"""
import pytest
from fastapi import HTTPException

import app.models  # noqa: F401
from app.models.approval import ApprovalRequest
from app.models.artifact_chain import ArtifactChain
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release
from app.services.release_machine import advance_backlog_item_phase, advance_release_phase


def _project(db, auth_user, name, project_type=None):
    project = Project(name=name, client_id=1, tenant_id=auth_user["tenant"].id)
    if project_type:
        project.project_type = project_type
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


# ── Service unit: the advance machine ───────────────────────────────────


def test_service_advance_matches_router_chain(db, auth_user, client):
    """Advancing an item through the effective template's phases via the
    SERVICE lands the same chain entries — same actions, same order, same
    payloads, same seq — as the router path produces."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, "Chain parity P", project_type="sdlc")

    svc_item = BacklogItem(tenant_id=tenant.id, project_id=project.id, title="Parity item")
    rt_item = BacklogItem(tenant_id=tenant.id, project_id=project.id, title="Parity item")
    db.add_all([svc_item, rt_item])
    db.commit()
    db.refresh(svc_item)
    db.refresh(rt_item)

    # Service path: Requirements → Design → Implementation (sdlc template)
    assert advance_backlog_item_phase(db, tenant, user, svc_item).current_phase == "Design"
    assert advance_backlog_item_phase(db, tenant, user, svc_item).current_phase == "Implementation"

    # Router path: the same two advances
    r1 = client.post(f"/api/backlog/{rt_item.id}/advance")
    r2 = client.post(f"/api/backlog/{rt_item.id}/advance")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["current_phase"] == "Design"
    assert r2.json()["current_phase"] == "Implementation"

    rows = (
        db.query(ArtifactChain)
        .filter(ArtifactChain.entity_type == "backlog_item")
        .order_by(ArtifactChain.entity_id, ArtifactChain.seq)
        .all()
    )
    svc = [
        (e.action, e.payload, e.seq, e.actor_id, e.actor_name)
        for e in rows
        if e.entity_id == svc_item.id
    ]
    rt = [
        (e.action, e.payload, e.seq, e.actor_id, e.actor_name)
        for e in rows
        if e.entity_id == rt_item.id
    ]
    expected = [
        ("advanced", {"title": "Parity item", "to_phase": "Design", "status": "In Progress"}, 1, user.id, user.name),
        ("advanced", {"title": "Parity item", "to_phase": "Implementation", "status": "In Progress"}, 2, user.id, user.name),
    ]
    assert svc == expected, "service path chain entries drifted"
    assert rt == expected, "router path chain entries drifted"


def test_service_advance_final_item_phase_400(db, auth_user):
    """An item at the template's last item phase 400s with the router's exact
    string (release stages are release-level — the release workflow owns them)."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, "Final phase P")

    item = BacklogItem(tenant_id=tenant.id, project_id=project.id, title="Final item")
    item.current_phase = "Ready for UAT"
    db.add(item)
    db.commit()
    db.refresh(item)

    with pytest.raises(HTTPException) as exc:
        advance_backlog_item_phase(db, tenant, user, item)
    assert exc.value.status_code == 400
    assert exc.value.detail == (
        "Item is at the final item phase (Ready for UAT). "
        "Add it to a release to continue through the release stages."
    )
    db.refresh(item)
    assert item.current_phase == "Ready for UAT"  # nothing moved


def test_service_release_gate_flow(db, auth_user):
    """The release gate flow runs through the service: Planning advance
    creates the gate approval, a second call reports pending, nothing moves."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, "Gate P")

    release = Release(tenant_id=tenant.id, project_id=project.id, version="3.0.0", name="RM", status="Planning")
    db.add(release)
    db.commit()
    db.refresh(release)

    first = advance_release_phase(db, tenant, user, release)
    assert first["approval_status"] == "created"
    assert first["pending_role"] == "Product Owner"
    assert first["target_phase"] == "In Progress"
    assert "Approval request #" in first["message"]
    assert db.query(ApprovalRequest).filter(ApprovalRequest.release_id == release.id).first() is not None

    second = advance_release_phase(db, tenant, user, release)
    assert second["approval_status"] == "pending"
    db.refresh(release)
    assert release.status == "Planning"  # the gate keeps the release in place


def test_service_release_guards_raise_400s(db, auth_user):
    """The terminal-state guards raise the byte-identical 400s from the
    pre-extraction router."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, "Guard P")

    for status, detail in [
        ("Released", "Release is already in Released state"),
        ("Cancelled", "Cannot advance a cancelled release"),
        ("Post-Release", "Release is already in the final phase (Post-Release)"),
    ]:
        release = Release(tenant_id=tenant.id, project_id=project.id, version="3.2.0", name=f"RG {status}", status=status)
        db.add(release)
        db.commit()
        db.refresh(release)

        with pytest.raises(HTTPException) as exc:
            advance_release_phase(db, tenant, user, release)
        assert exc.value.status_code == 400
        assert exc.value.detail == detail


# ── Delegation: the routers call the service ────────────────────────────


def test_releases_router_delegates_to_service(db, auth_user, client, monkeypatch):
    """POST /releases/{id}/advance invokes the service exactly once with the
    tenant-scoped fetch result; the router's response is the service's."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, "Delegate P")

    release = Release(tenant_id=tenant.id, project_id=project.id, version="3.3.0", name="RD", status="Planning")
    db.add(release)
    db.commit()
    db.refresh(release)

    calls = []

    def fake_advance(db_, tenant_, user_, release_):
        calls.append((db_, tenant_, user_, release_))
        return {"delegated": True}

    monkeypatch.setattr("app.routers.releases.advance_release_phase", fake_advance)
    resp = client.post(f"/api/releases/{release.id}/advance")

    assert resp.status_code == 200
    assert resp.json() == {"delegated": True}
    assert len(calls) == 1
    assert calls[0][0] is db
    assert calls[0][1].id == tenant.id
    assert calls[0][2].id == user.id
    assert calls[0][3].id == release.id


def test_backlog_router_delegates_to_service(db, auth_user, client, monkeypatch):
    """POST /backlog/{id}/advance invokes the service exactly once with the
    tenant-scoped fetch result; the router's response is the service's."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, "Delegate B P")

    item = BacklogItem(tenant_id=tenant.id, project_id=project.id, title="Delegated item")
    db.add(item)
    db.commit()
    db.refresh(item)

    calls = []

    def fake_advance(db_, tenant_, user_, item_):
        calls.append((db_, tenant_, user_, item_))
        return item_

    monkeypatch.setattr("app.routers.backlog.advance_backlog_item_phase", fake_advance)
    resp = client.post(f"/api/backlog/{item.id}/advance")

    assert resp.status_code == 200
    assert resp.json()["id"] == item.id
    assert len(calls) == 1
    assert calls[0][0] is db
    assert calls[0][1].id == tenant.id
    assert calls[0][2].id == user.id
    assert calls[0][3].id == item.id


def test_advance_404_stays_in_router(client):
    """The tenant-scoped fetch + 404 stay in the routers (request glue)."""
    assert client.post("/api/releases/999999/advance").status_code == 404
    assert client.post("/api/backlog/999999/advance").status_code == 404
