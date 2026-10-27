"""API tests for the R1 spine.

GET /api/today — needs-you aggregate + briefing (tenant-scoped)
GET /api/projects/{id}/brief — narrative from live data
GET /api/work — unified cross-project work list
"""

import pytest


@pytest.fixture
def project(client, db, auth_user):
    from app.models.project import Project

    p = Project(
        tenant_id=auth_user["tenant"].id,
        client_id=auth_user["user"].id,
        name="API R1 Project",
        status="Active",
    )
    db.add(p)
    db.commit()
    return p


def test_today_endpoint(client, project):
    r = client.get("/api/today")
    assert r.status_code == 200
    data = r.json()
    assert "needs_you" in data and "briefing" in data and "counts" in data
    assert data["briefing"]["verdict"] in ("on_track", "needs_attention", "at_risk")
    assert len(data["briefing"]["lines"]) == 3


def test_today_requires_auth(client):
    client.headers.pop("Authorization", None)
    r = client.get("/api/today")
    assert r.status_code in (401, 403)


def test_brief_endpoint(client, project):
    r = client.get(f"/api/projects/{project.id}/brief")
    assert r.status_code == 200
    data = r.json()
    assert "API R1 Project" in data["narrative"]
    assert data["stats"]["total"] == 0


def test_work_endpoint(client, project):
    r = client.get("/api/work")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["items"], list)


def test_work_blocked_filter(client, db, project, auth_user):
    from app.models.backlog_item import BacklogItem

    db.add(BacklogItem(project_id=project.id, title="Blocked one", status="Blocked", current_phase="Development", target_release="2026-01"))
    db.add(BacklogItem(project_id=project.id, title="Normal one", status="In Progress", current_phase="Development", target_release="2026-12"))
    db.commit()
    r = client.get("/api/work?filter=blocked")
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()["items"]]
    assert "Blocked one" in titles
    assert "Normal one" not in titles
