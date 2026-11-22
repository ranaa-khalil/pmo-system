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


# ─── Slice 3a: the extended ONE Work view payload ───

def test_work_payload_extended_fields(client, db, project, auth_user):
    """GET /api/work carries the 8 R2 columns on top of the 10 R1 columns."""
    from datetime import date

    from app.models.backlog_item import BacklogItem
    from app.models.comment import Comment
    from app.models.tag import Tag, backlog_item_tags

    user = auth_user["user"]
    item = BacklogItem(
        project_id=project.id,
        title="Payload probe",
        status="In Progress",
        current_phase="Development",
        item_type="Feature",
        epic="Onboarding",
        assigned_to=user.id,
        board_order=3,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 10),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    tag = Tag(tenant_id=auth_user["tenant"].id, name="urgent", color="rose")
    db.add(tag)
    db.commit()
    db.refresh(tag)
    db.execute(backlog_item_tags.insert().values(backlog_item_id=item.id, tag_id=tag.id))
    db.add(Comment(tenant_id=auth_user["tenant"].id, item_id=item.id, user_id=user.id, body="first"))
    db.add(Comment(tenant_id=auth_user["tenant"].id, item_id=item.id, user_id=user.id, body="second"))
    db.commit()

    r = client.get("/api/work")
    assert r.status_code == 200
    rows = r.json()["items"]
    row = next(i for i in rows if i["id"] == item.id)
    # the 8 new columns
    assert row["item_type"] == "Feature"
    assert row["epic"] == "Onboarding"
    assert row["assigned_to_name"] == user.name
    assert row["tags"] == [{"id": tag.id, "name": "urgent", "color": "rose"}]
    assert row["comment_count"] == 2
    assert row["board_order"] == 3
    assert row["start_date"] == "2026-11-01"
    assert row["end_date"] == "2026-11-10"
    # the 10 existing columns unchanged
    assert row["title"] == "Payload probe"
    assert row["project"] == project.name
    assert row["phase"] == "Development"
    assert row["status"] == "In Progress"
    assert row["priority"] == "Medium"
    assert row["assigned_to"] == user.id
    assert row["overdue"] is False
    assert row["blocked"] is False


def test_work_mine_filter_is_live(client, db, project, auth_user):
    """Mine works the moment an item is assigned — the payload enables the chip."""
    from app.models.backlog_item import BacklogItem

    user = auth_user["user"]
    db.add(BacklogItem(project_id=project.id, title="Assigned to me", assigned_to=user.id, current_phase="Design"))
    db.add(BacklogItem(project_id=project.id, title="Assigned to nobody", current_phase="Design"))
    db.commit()
    r = client.get("/api/work?filter=mine")
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()["items"]]
    assert "Assigned to me" in titles
    assert "Assigned to nobody" not in titles


def test_work_tag_filter_reads_payload_tags(client, db, project, auth_user):
    """tag_id filters via the M2M and the payload's tags[] carries the tag."""
    from app.models.backlog_item import BacklogItem
    from app.models.tag import Tag, backlog_item_tags

    item = BacklogItem(project_id=project.id, title="Tagged work", current_phase="Design")
    other = BacklogItem(project_id=project.id, title="Untagged work", current_phase="Design")
    db.add_all([item, other])
    db.commit()
    tag = Tag(tenant_id=auth_user["tenant"].id, name="infra", color="indigo")
    db.add(tag)
    db.commit()
    db.refresh(tag)
    db.execute(backlog_item_tags.insert().values(backlog_item_id=item.id, tag_id=tag.id))
    db.commit()

    r = client.get(f"/api/work?tag_id={tag.id}")
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()["items"]]
    assert "Tagged work" in titles
    assert "Untagged work" not in titles
    row = next(i for i in r.json()["items"] if i["title"] == "Tagged work")
    assert row["tags"][0]["name"] == "infra"


def test_work_overdue_filter(client, db, project):
    """Overdue filters on the payload's data (stale target_release + open status)."""
    from app.models.backlog_item import BacklogItem

    db.add(BacklogItem(project_id=project.id, title="Overdue one", status="In Progress", target_release="2026-01"))
    db.add(BacklogItem(project_id=project.id, title="Current one", status="In Progress", target_release="2099-12"))
    db.commit()
    r = client.get("/api/work?filter=overdue")
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()["items"]]
    assert "Overdue one" in titles
    assert "Current one" not in titles


def test_work_openapi_schema_shows_extended_payload(client):
    """OpenAPI describes the real shape: the 8 new fields on the work item."""
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/api/work"]["get"]
    schema_ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    list_name = schema_ref.split("/")[-1]
    item_ref = spec["components"]["schemas"][list_name]["properties"]["items"]["items"]["$ref"]
    item_name = item_ref.split("/")[-1]
    props = spec["components"]["schemas"][item_name]["properties"]
    for field in [
        "item_type", "epic", "assigned_to_name", "tags", "comment_count",
        "board_order", "start_date", "end_date",
    ]:
        assert field in props, f"{field} missing from the /api/work OpenAPI schema"
    for field in [
        "id", "title", "project", "phase", "status", "priority",
        "assigned_to", "target_release", "overdue", "blocked",
    ]:
        assert field in props, f"existing column {field} dropped from the /api/work OpenAPI schema"
