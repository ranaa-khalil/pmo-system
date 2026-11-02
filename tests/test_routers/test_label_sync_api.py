"""Tests for two-way tag ↔ GitHub label sync — GitHub Boards parity (R6).

sync-tags: repo labels land in the tenant tag pool (pull) and tenant tags
become repo labels (push). Export carries item tag names as labels. Import
links the issue's labels into the pool via the M2M. The GitHubService is
mocked — no live calls.
"""
import pytest

import app.models  # noqa: F401
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tag import Tag


@pytest.fixture()
def tag_world(client, db, auth_user):
    """A project with a configured repo and one tagged item."""
    tenant = auth_user["tenant"]
    project = Project(name="Tag P", client_id=1, tenant_id=tenant.id, github_repo="opex-sa/CloudGate")
    db.add(project)
    db.commit()
    db.refresh(project)
    item = BacklogItem(tenant_id=tenant.id, project_id=project.id, title="Tagged item", current_phase="Development")
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"tenant": tenant, "project": project, "item": item}


def _fake_gh(labels=None, ensure_ok=True):
    captured = {"ensure": [], "export_labels": None}

    class FakeGH:
        def list_labels(self, repo):
            return labels or []

        def ensure_label(self, repo, name, color="5B6EE1", description=""):
            captured["ensure"].append((name, color))
            return ensure_ok

        def export_backlog_item(self, **kwargs):
            captured["export_labels"] = kwargs.get("labels")
            return {"number": 9, "html_url": "https://github.com/opex-sa/CloudGate/issues/9"}

        def get_issue(self, repo, number):
            return None

        def close(self):
            pass

    return FakeGH(), captured


def test_sync_tags_pushes_and_pulls(tag_world, client, db, monkeypatch):
    tenant, project = tag_world["tenant"], tag_world["project"]
    # Tenant pool: two tags
    db.add_all([
        Tag(tenant_id=tenant.id, name="frontend", color="violet"),
        Tag(tenant_id=tenant.id, name="payments", color="emerald"),
    ])
    db.commit()
    # Repo already has one label that matches nothing in the pool + one overlap
    fake, captured = _fake_gh(labels=[
        {"name": "design", "color": "8B5CF6"},
        {"name": "frontend", "color": "999999"},  # overlap — not pulled again
    ])
    import app.routers.github_sync as gh_router
    monkeypatch.setattr(gh_router.settings, "github_token", "fake-token")
    monkeypatch.setattr(gh_router, "GitHubService", lambda token=None: fake)

    resp = client.post(f"/api/projects/{project.id}/github/sync-tags")
    assert resp.status_code == 200
    data = resp.json()
    assert data["pulled"] == ["design"]
    # Push: both pool tags that don't exist on the repo yet (design got pulled,
    # frontend exists on the repo, payments pushed)
    assert "payments" in data["pushed"]
    assert "frontend" not in data["pushed"]  # already on the repo
    assert ("payments", "10B981") in captured["ensure"]  # emerald hex
    # Pull landed in the pool with a palette color
    tag = db.query(Tag).filter(Tag.tenant_id == tenant.id, Tag.name == "design").first()
    assert tag is not None
    assert tag.color == "violet"


def test_sync_tags_requires_repo(tag_world, client, db, monkeypatch):
    tag_world["project"].github_repo = None
    db.commit()
    import app.routers.github_sync as gh_router
    monkeypatch.setattr(gh_router.settings, "github_token", "fake-token")
    resp = client.post(f"/api/projects/{tag_world['project'].id}/github/sync-tags")
    assert resp.status_code == 400


def test_export_carries_item_tags(tag_world, client, db, monkeypatch):
    tenant, project, item = tag_world["tenant"], tag_world["project"], tag_world["item"]
    t = Tag(tenant_id=tenant.id, name="checkout", color="blue")
    db.add(t)
    db.commit()
    item.tags.append(t)
    item.current_phase = "Development"
    item.status = "In Progress"
    db.commit()

    fake, captured = _fake_gh(labels=[])
    import app.routers.github_sync as gh_router
    monkeypatch.setattr(gh_router.settings, "github_token", "fake-token")
    monkeypatch.setattr(gh_router, "GitHubService", lambda token=None: fake)

    resp = client.post(f"/api/projects/{project.id}/github/export", json={})
    assert resp.status_code == 200
    assert "checkout" in (captured["export_labels"] or [])


def test_import_links_labels_to_pool(tag_world, client, db, monkeypatch):
    tenant, project, item = tag_world["tenant"], tag_world["project"], tag_world["item"]
    item.current_phase = "Development"
    item.github_issue_number = 12
    db.commit()

    class FakeGH:
        def get_issue(self, repo, number):
            return {
                "state": "open",
                "labels": ["api", "urgent"],
                "assignees": [],
            }

        def close(self):
            pass

    import app.routers.github_sync as gh_router
    monkeypatch.setattr(gh_router.settings, "github_token", "fake-token")
    monkeypatch.setattr(gh_router, "GitHubService", lambda token=None: FakeGH())

    resp = client.post(f"/api/projects/{project.id}/github/import")
    assert resp.status_code == 200
    # Labels landed in the pool
    names = {t.name for t in db.query(Tag).filter(Tag.tenant_id == tenant.id).all()}
    assert {"api", "urgent"} <= names
    # And are linked to the item
    db.refresh(item)
    assert {t.name for t in item.tags} >= {"api", "urgent"}
