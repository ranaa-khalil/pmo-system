"""Tests for the releases API — CRUD, items, advance lifecycle, next-version.

Releases are tenant-scoped: another tenant's release 404s. The advance
endpoint walks Planned → In Progress → UAT → Released → Archived. Item add/
remove syncs backlog item release_id. Auto-version suggests the next semver.
"""
import pytest

import app.models  # noqa: F401
from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release, ReleaseItem


@pytest.fixture()
def release_world(client, db, auth_user):
    """The shared owner + a project."""
    tenant = auth_user["tenant"]
    project = Project(name="Release P", client_id=1, tenant_id=tenant.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "project": project}


def test_create_and_list_release(release_world, client):
    project = release_world["project"]
    resp = client.post(f"/api/projects/{project.id}/releases", json={
        "version": "1.0.0", "name": "Launch", "status": "Planned",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["version"] == "1.0.0"

    rows = client.get(f"/api/projects/{project.id}/releases").json()
    assert len(rows) == 1


def test_get_release_with_items(release_world, client, db):
    project = release_world["project"]
    release = Release(tenant_id=release_world["tenant"].id, project_id=project.id, version="1.1.0", name="R2", status="In Progress")
    db.add(release)
    db.commit()
    db.refresh(release)

    data = client.get(f"/api/releases/{release.id}").json()
    assert data["id"] == release.id
    assert "items" in data


def test_update_release(release_world, client, db):
    project = release_world["project"]
    release = Release(tenant_id=release_world["tenant"].id, project_id=project.id, version="1.2.0", name="R3", status="Planned")
    db.add(release)
    db.commit()
    db.refresh(release)

    resp = client.put(f"/api/releases/{release.id}", json={"status": "In Progress", "notes": "moving"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "In Progress"


def test_advance_release_gate_flow(release_world, client, db):
    """Advance is RACI-gated: it creates an approval, not an immediate move."""
    project = release_world["project"]
    release = Release(tenant_id=release_world["tenant"].id, project_id=project.id, version="1.3.0", name="R4", status="Planning")
    db.add(release)
    db.commit()
    db.refresh(release)

    # First advance → creates a gate approval for the next phase
    resp = client.post(f"/api/releases/{release.id}/advance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["approval_status"] == "created"
    assert data["pending_role"]
    assert data["target_phase"] == "In Progress"
    assert db.query(ApprovalRequest).filter(ApprovalRequest.release_id == release.id).first() is not None

    # Second advance while pending → reports the pending status, doesn't move
    resp = client.post(f"/api/releases/{release.id}/advance")
    assert resp.status_code == 200
    assert resp.json()["approval_status"] == "pending"
    db.refresh(release)
    assert release.status == "Planning"


def test_advance_released_release_400(release_world, client, db):
    project = release_world["project"]
    release = Release(tenant_id=release_world["tenant"].id, project_id=project.id, version="1.3.1", name="R4b", status="Released")
    db.add(release)
    db.commit()
    db.refresh(release)

    resp = client.post(f"/api/releases/{release.id}/advance")
    assert resp.status_code == 400
    assert "Released" in resp.json()["detail"]


def test_add_and_remove_release_item(release_world, client, db):
    tenant = release_world["tenant"]
    project = release_world["project"]
    release = Release(tenant_id=tenant.id, project_id=project.id, version="1.4.0", name="R5", status="Planned")
    db.add(release)
    db.commit()
    db.refresh(release)
    item = BacklogItem(tenant_id=tenant.id, project_id=project.id, title="Item A", current_phase="Development")
    db.add(item)
    db.commit()
    db.refresh(item)

    # Add
    resp = client.post(f"/api/releases/{release.id}/items/{item.id}")
    assert resp.status_code == 201
    linked = db.query(ReleaseItem).filter(
        ReleaseItem.release_id == release.id, ReleaseItem.backlog_item_id == item.id,
    ).first()
    assert linked is not None

    # Remove
    resp = client.delete(f"/api/releases/{release.id}/items/{item.id}")
    assert resp.status_code == 204
    linked = db.query(ReleaseItem).filter(
        ReleaseItem.release_id == release.id, ReleaseItem.backlog_item_id == item.id,
    ).first()
    assert linked is None


def test_next_version_suggestion(release_world, client, db):
    """next-version suggests major.minor+1.0 with no existing releases."""
    project = release_world["project"]
    resp = client.get(f"/api/projects/{project.id}/releases/next-version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"].count(".") == 2
    assert data["bump"] == "initial"


def test_release_other_tenant_404(release_world, client, db):
    from app.models.tenant import Tenant

    other = Tenant(name="Other Rel", slug="other-rel", plan="team")
    db.add(other)
    db.commit()
    db.refresh(other)
    other_release = Release(tenant_id=other.id, project_id=1, version="9.9.9", name="Hidden", status="Planned")
    db.add(other_release)
    db.commit()
    db.refresh(other_release)

    resp = client.get(f"/api/releases/{other_release.id}")
    assert resp.status_code == 404


def test_delete_release(release_world, client, db):
    project = release_world["project"]
    release = Release(tenant_id=release_world["tenant"].id, project_id=project.id, version="1.5.0", name="Temp", status="Planned")
    db.add(release)
    db.commit()
    db.refresh(release)

    resp = client.delete(f"/api/releases/{release.id}")
    assert resp.status_code == 204
    assert db.query(Release).filter(Release.id == release.id).first() is None
