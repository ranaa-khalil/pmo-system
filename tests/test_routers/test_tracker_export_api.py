"""Tests for the feature tracker rollup + xlsx export (Bayan parity)."""
import pytest

import app.models  # noqa: F401
from app.models.acceptance_check import AcceptanceCheck
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User


@pytest.fixture()
def tracker_world(client, db):
    tenant = Tenant(name="Tracker Co", slug="tracker-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-tracker@copilot.test", name="PM", hashed_password="x",
              system_role="project_manager")
    db.add(pm)
    db.commit()
    db.refresh(pm)
    pm.active_tenant_id = tenant.id
    db.commit()
    db.add(TenantMembership(user_id=pm.id, tenant_id=tenant.id, role="owner"))
    project = Project(name="Tracker Proj", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    f1 = BacklogItem(title="Discovery", project_id=project.id, tenant_id=tenant.id,
                     item_type="Feature", epic="E1", primary_actor="User",
                     personas="Reader, Student", status="In Progress")
    f2 = BacklogItem(title="Q&A", project_id=project.id, tenant_id=tenant.id,
                     item_type="Feature", epic="E1", status="Draft")
    non_feature = BacklogItem(title="A bug", project_id=project.id, tenant_id=tenant.id, item_type="Bug")
    db.add_all([f1, f2, non_feature])
    db.commit()
    db.refresh(f1)
    db.refresh(f2)
    # f2 depends on f1
    f2.depends_on_items.append(f1) if hasattr(f2, "depends_on_items") else None
    db.add(AcceptanceCheck(tenant_id=tenant.id, item_id=f1.id, check_order=1, text="Check one", result="Pass"))
    db.add(AcceptanceCheck(tenant_id=tenant.id, item_id=f1.id, check_order=2, text="Check two", result="Not tested"))
    sub1 = BacklogItem(title="Build task", project_id=project.id, tenant_id=tenant.id,
                       item_type="Task", status="Done", parent_item_id=f1.id)
    db.add(sub1)
    db.commit()
    return {"tenant": tenant, "pm": pm, "project": project, "f1": f1, "f2": f2}


def _as(client, user):
    from app.services.auth import create_access_token
    client.headers.update({"Authorization": f"Bearer {create_access_token(data={'sub': str(user.id)})}"})


def test_feature_tracker_rollup(tracker_world, client):
    pm, project, f1 = tracker_world["pm"], tracker_world["project"], tracker_world["f1"]
    _as(client, pm)
    resp = client.get(f"/api/projects/{project.id}/feature-tracker")
    assert resp.status_code == 200
    rows = resp.json()
    # Only Feature items
    assert all(r["item_type"] if "item_type" in r else True for r in rows)
    titles = {r["title"] for r in rows}
    assert "Discovery" in titles and "Q&A" in titles
    assert "A bug" not in titles
    row = next(r for r in rows if r["title"] == "Discovery")
    assert row["checks_passed"] == 1 and row["checks_total"] == 2
    assert row["tasks_done"] == 1 and row["tasks_total"] == 1
    assert row["progress"] == 0.5
    assert row["used_by"] == "User"
    assert row["personas"] == "Reader, Student"


def test_export_tracker_xlsx(tracker_world, client):
    pm, project = tracker_world["pm"], tracker_world["project"]
    _as(client, pm)
    resp = client.get(f"/api/projects/{project.id}/export/tracker.xlsx")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "build-tracker" in resp.headers.get("content-disposition", "")
    # Parse the workbook
    import io

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(resp.content))
    assert "Features" in wb.sheetnames
    assert "Checklist" in wb.sheetnames
    ws = wb["Features"]
    # Header row + 2 feature rows
    headers = [c.value for c in ws[3]]
    assert "ID" in headers and "Epic" in headers and "Progress" in headers
    data_rows = [r for r in ws.iter_rows(min_row=4) if r[1].value]
    assert len(data_rows) == 2
    ws2 = wb["Checklist"]
    task_rows = [r for r in ws2.iter_rows(min_row=3) if r[0].value and r[2].value]
    assert len(task_rows) == 1
    assert task_rows[0][2].value == "Build task"


def test_export_requires_project(tracker_world, client):
    pm = tracker_world["pm"]
    _as(client, pm)
    resp = client.get("/api/projects/999999/export/tracker.xlsx")
    assert resp.status_code == 404
