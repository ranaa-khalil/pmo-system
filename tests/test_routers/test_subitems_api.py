"""Tests for backlog sub-items — GitHub Boards parity (R6).

parent_item_id self-FK, one level only (a sub-item can never itself have a
parent), sub-items listed via /subitems, and a /tree endpoint with a progress
rollup (done / total).
"""
import pytest

import app.models  # noqa: F401


@pytest.fixture()
def subitem_world(client):
    """A project with one parent item."""
    cid = client.post("/api/clients", json={"name": "Sub Co"}).json()["id"]
    project = client.post("/api/projects", json={"name": "Parent Proj", "client_id": cid}).json()
    parent = client.post(f"/api/projects/{project['id']}/backlog", json={
        "project_id": project["id"], "title": "Epic: checkout redesign",
    }).json()
    return {"project": project, "parent": parent}


def test_create_subitem(client, subitem_world):
    project, parent = subitem_world["project"], subitem_world["parent"]
    resp = client.post(f"/api/projects/{project['id']}/backlog", json={
        "project_id": project["id"], "title": "Split payment step",
        "parent_item_id": parent["id"],
    })
    assert resp.status_code == 201
    row = resp.json()
    assert row["parent_item_id"] == parent["id"]


def test_subitems_listed(client, subitem_world):
    project, parent = subitem_world["project"], subitem_world["parent"]
    client.post(f"/api/projects/{project['id']}/backlog", json={
        "project_id": project["id"], "title": "Split payment step",
        "parent_item_id": parent["id"],
    })
    client.post(f"/api/projects/{project['id']}/backlog", json={
        "project_id": project["id"], "title": "Guest checkout path",
        "parent_item_id": parent["id"],
    })
    subs = client.get(f"/api/backlog/{parent['id']}/subitems").json()
    assert {s["title"] for s in subs} == {"Split payment step", "Guest checkout path"}


def test_subitem_cannot_nest_400(client, subitem_world):
    project, parent = subitem_world["project"], subitem_world["parent"]
    sub = client.post(f"/api/projects/{project['id']}/backlog", json={
        "project_id": project["id"], "title": "Level 1", "parent_item_id": parent["id"],
    }).json()
    resp = client.post(f"/api/projects/{project['id']}/backlog", json={
        "project_id": project["id"], "title": "Level 2", "parent_item_id": sub["id"],
    })
    assert resp.status_code == 400


def test_unknown_parent_400(client, subitem_world):
    project = subitem_world["project"]
    resp = client.post(f"/api/projects/{project['id']}/backlog", json={
        "project_id": project["id"], "title": "Orphan", "parent_item_id": 999999,
    })
    assert resp.status_code == 400


def test_cross_project_parent_400(client, subitem_world):
    project = subitem_world["project"]
    cid = client.post("/api/clients", json={"name": "Other Co"}).json()["id"]
    other = client.post("/api/projects", json={"name": "Other Proj", "client_id": cid}).json()
    resp = client.post(f"/api/projects/{other['id']}/backlog", json={
        "project_id": other["id"], "title": "Cross-project child",
        "parent_item_id": subitem_world["parent"]["id"],
    })
    assert resp.status_code == 400


def test_tree_rollup(client, subitem_world):
    project, parent = subitem_world["project"], subitem_world["parent"]
    s1 = client.post(f"/api/projects/{project['id']}/backlog", json={
        "project_id": project["id"], "title": "S1", "parent_item_id": parent["id"],
    }).json()
    client.post(f"/api/projects/{project['id']}/backlog", json={
        "project_id": project["id"], "title": "S2", "parent_item_id": parent["id"],
    })
    client.put(f"/api/backlog/{s1['id']}", json={"status": "Done"})
    tree = client.get(f"/api/backlog/{parent['id']}/tree").json()
    assert tree["id"] == parent["id"]
    assert len(tree["children"]) == 2
    assert tree["rollup"] == {"total": 2, "done": 1, "pct": 50}


def test_tree_empty_rollup(client, subitem_world):
    parent = subitem_world["parent"]
    tree = client.get(f"/api/backlog/{parent['id']}/tree").json()
    assert tree["rollup"] == {"total": 0, "done": 0, "pct": 0}


def test_subitems_404_unknown_item(client):
    resp = client.get("/api/backlog/999999/subitems")
    assert resp.status_code == 404
