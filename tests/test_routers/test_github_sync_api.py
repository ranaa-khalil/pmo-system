"""Tests for the GitHub sync API — board config + sync status (offline paths).

The GitHubService is mocked: no live calls in CI. Covered here are the
DB-backed paths: config get/update (auto-creates a default row), sync-status
counts, and the validation errors (no repo, no token). Export/import are
exercised with the GraphQL client stubbed out.
"""
import pytest

import app.models  # noqa: F401
from app.models.backlog_item import BacklogItem
from app.models.project import Project


@pytest.fixture()
def gh_world(client, db, auth_user):
    """A project; no GitHub token configured."""
    tenant = auth_user["tenant"]
    project = Project(name="GH P", client_id=1, tenant_id=tenant.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "project": project}


def test_get_config_auto_creates_default(gh_world, client):
    project = gh_world["project"]
    resp = client.get(f"/api/projects/{project.id}/github-config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["repo"] is None
    assert data["default_labels"] == "from-pmo"
    assert data["auto_export"] is False
    # Second call returns the same row
    resp2 = client.get(f"/api/projects/{project.id}/github-config")
    assert resp2.json()["id"] == data["id"]


def test_update_config(gh_world, client):
    project = gh_world["project"]
    resp = client.put(f"/api/projects/{project.id}/github-config", json={
        "repo": "opex-sa/CloudGate", "default_labels": "from-pmo,priority-high",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["repo"] == "opex-sa/CloudGate"
    assert data["default_labels"] == "from-pmo,priority-high"


def test_sync_status_counts(gh_world, client, db):
    project = gh_world["project"]
    db.add(BacklogItem(tenant_id=gh_world["tenant"].id, project_id=project.id, title="Synced", current_phase="Development", github_issue_number=42))
    db.add(BacklogItem(tenant_id=gh_world["tenant"].id, project_id=project.id, title="Unsynced", current_phase="Requirements"))
    db.commit()

    resp = client.get(f"/api/projects/{project.id}/github/sync-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 2
    assert data["synced_items"] == 1
    assert data["unsynced_items"] == 1


def test_sync_status_other_tenant_project_404(gh_world, client, db):
    from app.models.tenant import Tenant

    other = Tenant(name="Other GH", slug="other-gh", plan="team")
    db.add(other)
    db.commit()
    db.refresh(other)
    other_project = Project(name="Hidden", client_id=1, tenant_id=other.id)
    db.add(other_project)
    db.commit()
    db.refresh(other_project)

    resp = client.get(f"/api/projects/{other_project.id}/github/sync-status")
    assert resp.status_code == 404


def test_export_requires_repo(gh_world, client, monkeypatch):
    """Export without a repo → 400 with a helpful message."""
    project = gh_world["project"]
    resp = client.post(f"/api/projects/{project.id}/github/export", json={})
    assert resp.status_code == 400
    assert "repo" in resp.json()["detail"].lower()


def test_list_projects_requires_token(gh_world, client, monkeypatch):
    """Listing boards without any configured token → 400."""
    import app.routers.github_sync as gh_router

    monkeypatch.setattr(gh_router.settings, "github_token", "")
    project = gh_world["project"]
    resp = client.get(f"/api/projects/{project.id}/github/projects")
    assert resp.status_code == 400
    assert "token" in resp.json()["detail"].lower()


def test_export_with_mocked_service(gh_world, client, db, monkeypatch, auth_user):
    """Export creates issues via the service and records them on the items."""
    tenant = gh_world["tenant"]
    project = gh_world["project"]

    # Configure a repo on the project
    project.github_repo = "opex-sa/CloudGate"
    db.commit()

    item = BacklogItem(tenant_id=tenant.id, project_id=project.id, title="Exportable", current_phase="Development", status="In Progress")
    db.add(item)
    db.commit()
    db.refresh(item)

    captured = {}

    class FakeGH:
        def export_backlog_item(self, **kwargs):
            captured["repo"] = kwargs.get("repo")
            captured["title"] = kwargs.get("title")
            return {"number": 7, "html_url": "https://github.com/opex-sa/CloudGate/issues/7"}

        def close(self):
            pass

    import app.routers.github_sync as gh_router

    monkeypatch.setattr(gh_router.settings, "github_token", "fake-token")
    monkeypatch.setattr(gh_router, "GitHubService", lambda token=None: FakeGH())

    resp = client.post(f"/api/projects/{project.id}/github/export", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["exported"] == 1
    assert captured["repo"] == "opex-sa/CloudGate"
    assert captured["title"] == "Exportable"

    db.refresh(item)
    assert item.github_issue_number == 7
    assert item.github_issue_url.endswith("/issues/7")
    assert item.github_synced_at


def test_export_skips_already_synced(gh_world, client, db, monkeypatch):
    """Explicit item_ids that are already synced are skipped, not re-exported."""
    tenant = gh_world["tenant"]
    project = gh_world["project"]
    project.github_repo = "opex-sa/CloudGate"
    synced = BacklogItem(tenant_id=tenant.id, project_id=project.id, title="Already", current_phase="Development", github_issue_number=5)
    db.add(synced)
    db.commit()
    db.refresh(synced)

    class FakeGH:
        def export_backlog_item(self, **kwargs):  # pragma: no cover — must not be called
            raise AssertionError("already-synced item must not be re-exported")

        def close(self):
            pass

    import app.routers.github_sync as gh_router

    monkeypatch.setattr(gh_router.settings, "github_token", "fake-token")
    monkeypatch.setattr(gh_router, "GitHubService", lambda token=None: FakeGH())

    data = client.post(f"/api/projects/{project.id}/github/export", json={"item_ids": [synced.id]}).json()
    assert data["total"] == 1
    assert data["skipped"] == 1
    assert data["details"][0]["reason"] == "Already synced"


def test_export_auto_omits_already_synced(gh_world, client, db, monkeypatch):
    """The auto-export query never even selects synced items."""
    tenant = gh_world["tenant"]
    project = gh_world["project"]
    project.github_repo = "opex-sa/CloudGate"
    db.add(BacklogItem(tenant_id=tenant.id, project_id=project.id, title="Already", current_phase="Development", github_issue_number=5))
    db.commit()

    class FakeGH:
        def export_backlog_item(self, **kwargs):  # pragma: no cover
            raise AssertionError("must not be called")

        def close(self):
            pass

    import app.routers.github_sync as gh_router

    monkeypatch.setattr(gh_router.settings, "github_token", "fake-token")
    monkeypatch.setattr(gh_router, "GitHubService", lambda token=None: FakeGH())

    data = client.post(f"/api/projects/{project.id}/github/export", json={}).json()
    assert data["total"] == 0
